from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.payments.models import ModeOfPayment
from apps.settings.models import Branch
from apps.staff.models import OpeningPayment, POSOpeningEntry
from apps.users.models import CustomUser


class POSOpeningEntryTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.user = CustomUser.objects.create_user(
            username="cashier@test.com", password="testpass123", email="cashier@test.com"
        )
        cls.cash_mode = ModeOfPayment.objects.create(name="Test Cash", type="CASH")
        cls.bank_mode = ModeOfPayment.objects.create(name="Test Bank", type="BANK")
        cls.entry = POSOpeningEntry.objects.create(
            branch=cls.branch,
            cashier=cls.user,
            posting_date="2026-07-24",
        )
        OpeningPayment.objects.create(
            opening_entry=cls.entry, mode_of_payment=cls.cash_mode, opening_amount=Decimal("50000")
        )
        OpeningPayment.objects.create(
            opening_entry=cls.entry, mode_of_payment=cls.bank_mode, opening_amount=Decimal("0")
        )


class POSOpeningEntryModelTest(POSOpeningEntryTestBase):
    def test_str(self):
        self.assertIn("Main Branch", str(self.entry))

    def test_save_auto_assigns_branch(self):
        """Auto-assign branch from Branch.get_default() on save."""
        entry2 = POSOpeningEntry(cashier=self.user)
        entry2.save()
        self.assertEqual(entry2.branch, self.branch)

    def test_is_open_starts_false(self):
        self.assertFalse(self.entry.is_open)
        self.assertFalse(self.entry.is_closed)

    def test_submit_flips_status(self):
        self.entry.submit()
        self.assertEqual(self.entry.status, POSOpeningEntry.SUBMITTED)
        self.assertTrue(self.entry.is_open)
        self.assertFalse(self.entry.is_closed)

    def test_submit_idempotent_when_already_submitted(self):
        self.entry.submit()
        self.entry.submit()
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, POSOpeningEntry.SUBMITTED)

    def test_submit_does_nothing_when_cancelled(self):
        self.entry.status = POSOpeningEntry.CANCELLED
        self.entry.save()
        self.entry.submit()
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, POSOpeningEntry.CANCELLED)

    def test_cancel_flips_to_cancelled(self):
        self.entry.cancel(by_user=self.user)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, POSOpeningEntry.CANCELLED)
        self.assertEqual(self.entry.cancelled_by, self.user)
        self.assertIsNotNone(self.entry.cancelled_at)

    def test_cancel_idempotent_when_already_cancelled(self):
        self.entry.cancel(by_user=self.user)
        cancelled_at = self.entry.cancelled_at
        self.entry.cancel(by_user=self.user)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.cancelled_at, cancelled_at)

    def test_is_closed_when_closing_entry_set(self):
        self.entry.submit()
        from apps.staff.models import ClosingPayment, POSClosingEntry

        closing = POSClosingEntry.objects.create(
            branch=self.branch,
            opening_entry=self.entry,
            cashier=self.user,
        )
        for op in self.entry.opening_payments.all():
            ClosingPayment.objects.create(
                closing_entry=closing,
                mode_of_payment=op.mode_of_payment,
                opening_amount=op.opening_amount,
                expected_amount=op.opening_amount,
                closing_amount=op.opening_amount,
            )
        # Submitting the closing flips the opening to Closed.
        closing.submit()
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_closed)
        self.assertIsNotNone(self.entry.closing_entry)

    def test_ordering(self):
        # Default ordering is `-period_start_date`
        names = list(POSOpeningEntry.objects.values_list("branch__name", flat=True))
        self.assertEqual(len(names), 1)

    def test_cannot_have_two_open_shifts_same_branch(self):
        """Reject if a second open shift is created for the same branch.

        Covers the historical regression: clean() used to gate on
        `status == SUBMITTED`, but the view calls full_clean() *before*
        submit() flips the status, so the check was skipped and two DRAFTs
        could both pass validation then both submit. The fix makes clean()
        fire when status is DRAFT (about to be submitted) too.
        """
        self.entry.submit()  # status=SUBMITTED, closing_entry=NULL → is_open=True
        # New DRAFT entry — this is the state the view's full_clean() runs on.
        new_entry = POSOpeningEntry(
            branch=self.branch,
            cashier=self.user,
            posting_date="2026-07-24",
        )
        with self.assertRaises(ValidationError) as ctx:
            new_entry.full_clean()
        self.assertIn("branch", ctx.exception.message_dict)

    def test_submit_blocks_second_open_shift_same_branch(self):
        """Regression: submit() must re-check the unique-Open rule inside
        a transaction, so a concurrent submit that bypassed full_clean()
        (or a caller that forgets to call it) is still blocked."""
        self.entry.submit()
        new_entry = POSOpeningEntry.objects.create(
            branch=self.branch,
            cashier=self.user,
            posting_date="2026-07-24",
        )
        with self.assertRaises(ValidationError) as ctx:
            new_entry.submit()
        self.assertIn("branch", ctx.exception.message_dict)
        # The failed submit must NOT have flipped the status.
        new_entry.refresh_from_db()
        self.assertEqual(new_entry.status, POSOpeningEntry.DRAFT)
        # Only one Open shift remains.
        self.assertEqual(
            POSOpeningEntry.objects.filter(
                branch=self.branch, status=POSOpeningEntry.SUBMITTED, closing_entry__isnull=True
            ).count(),
            1,
        )

    def test_two_open_shifts_different_branches_allowed(self):
        """Different branches can each have their own Open shift."""
        self.entry.submit()
        other_branch = Branch.objects.create(name="Other Branch")
        other_entry = POSOpeningEntry.objects.create(
            branch=other_branch,
            cashier=self.user,
            posting_date="2026-07-24",
        )
        OpeningPayment.objects.create(
            opening_entry=other_entry, mode_of_payment=self.cash_mode, opening_amount=Decimal("1000")
        )
        # Must not raise.
        other_entry.full_clean()
        other_entry.submit()
        self.assertTrue(other_entry.is_open)
        self.assertTrue(self.entry.is_open)


class OpeningPaymentModelTest(POSOpeningEntryTestBase):
    def test_str(self):
        op = self.entry.opening_payments.get(mode_of_payment=self.cash_mode)
        self.assertIn("Test Cash", str(op))

    def test_unique_mode_per_entry(self):
        from django.db.utils import IntegrityError

        with self.assertRaises(IntegrityError):
            OpeningPayment.objects.create(
                opening_entry=self.entry,
                mode_of_payment=self.cash_mode,
                opening_amount=Decimal("0"),
            )

    def test_protect_on_mode_delete(self):
        from django.db.utils import IntegrityError

        with self.assertRaises(IntegrityError):
            self.cash_mode.delete()

    def test_ordering_alphabetical(self):
        names = list(self.entry.opening_payments.values_list("mode_of_payment__name", flat=True))
        self.assertEqual(names, sorted(names))

    def test_default_opening_amount_zero(self):
        op = OpeningPayment(opening_entry=self.entry, mode_of_payment=self.cash_mode)
        self.assertEqual(op.opening_amount, Decimal("0"))

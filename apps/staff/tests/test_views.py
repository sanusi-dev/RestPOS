from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.accounting.tests.helpers import setup_chart_of_accounts
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import Restaurant
from apps.staff.models import OpeningPayment, POSOpeningEntry
from apps.staff.services import submit_closing_entry
from apps.users.models import CustomUser


class StaffViewTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username="manager@test.com", password="testpass123", email="manager@test.com"
        )
        mgr, _ = Group.objects.get_or_create(name="RestPOS Manager")
        cls.user.groups.add(mgr)
        cls.restaurant = Restaurant.objects.create(company="Staff Views Co")
        cls.accounts = setup_chart_of_accounts(cls.restaurant)
        cls.cash_mode = ModeOfPayment.objects.create(name="Test Cash", type="CASH")
        cls.bank_mode = ModeOfPayment.objects.create(name="Test Bank", type="BANK")
        PaymentGLMapping.objects.create(mode_of_payment=cls.cash_mode, default_account=cls.accounts["cash"])
        PaymentGLMapping.objects.create(mode_of_payment=cls.bank_mode, default_account=cls.accounts["bank"])
        cls.entry = POSOpeningEntry.objects.create(
            cashier=cls.user,
            posting_date="2026-07-24",
        )
        OpeningPayment.objects.create(
            opening_entry=cls.entry,
            mode_of_payment=cls.cash_mode,
            opening_amount=Decimal("50000"),
        )
        OpeningPayment.objects.create(
            opening_entry=cls.entry,
            mode_of_payment=cls.bank_mode,
            opening_amount=Decimal("0"),
        )

    def setUp(self):
        self.client.login(username="manager@test.com", password="testpass123")


class TestLoginRequired(TestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("staff:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_opening_list_requires_login(self):
        response = self.client.get(reverse("staff:opening_entry_list"))
        self.assertEqual(response.status_code, 302)

    def test_closing_list_requires_login(self):
        response = self.client.get(reverse("staff:closing_entry_list"))
        self.assertEqual(response.status_code, 302)


class TestStaffDashboard(StaffViewTestBase):
    def test_dashboard_200(self):
        response = self.client.get(reverse("staff:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Current Shift State")

    def test_dashboard_shows_no_open_shift_state(self):
        response = self.client.get(reverse("staff:dashboard"))
        self.assertContains(response, "No open shift")


class TestPOSOpeningEntryViews(StaffViewTestBase):
    def test_list_200(self):
        response = self.client.get(reverse("staff:opening_entry_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{self.entry.pk}")

    def test_create_get(self):
        response = self.client.get(reverse("staff:opening_entry_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open Shift")

    def test_create_post(self):
        response = self.client.post(
            reverse("staff:opening_entry_create"),
            data={f"mop_{self.cash_mode.pk}": "30000"},
        )
        self.assertEqual(response.status_code, 302)
        entry = POSOpeningEntry.objects.exclude(pk=self.entry.pk).get()
        cash_row = entry.opening_payments.get(mode_of_payment=self.cash_mode)
        self.assertEqual(cash_row.opening_amount, Decimal("30000"))

    def test_create_post_captures_all_methods(self):
        """Both cash and electronic mode opening balances are persisted."""
        response = self.client.post(
            reverse("staff:opening_entry_create"),
            data={
                f"mop_{self.cash_mode.pk}": "25000",
                f"mop_{self.bank_mode.pk}": "120000",
            },
        )
        self.assertEqual(response.status_code, 302)
        entry = POSOpeningEntry.objects.exclude(pk=self.entry.pk).get()
        # One opening row per active ModeOfPayment (mirrors ERPNext's
        # pos_opening_entry.js secondary-payment pre-population).
        active_count = ModeOfPayment.objects.filter(enabled=True).count()
        self.assertEqual(entry.opening_payments.count(), active_count)
        self.assertEqual(
            entry.opening_payments.get(mode_of_payment=self.cash_mode).opening_amount,
            Decimal("25000"),
        )
        self.assertEqual(
            entry.opening_payments.get(mode_of_payment=self.bank_mode).opening_amount,
            Decimal("120000"),
        )

    def test_create_post_defaults_blank_to_zero(self):
        """Blank fields coerce to 0 (matches the form's initial=0 default)."""
        response = self.client.post(
            reverse("staff:opening_entry_create"),
            data={f"mop_{self.cash_mode.pk}": "25000"},
        )
        self.assertEqual(response.status_code, 302)
        entry = POSOpeningEntry.objects.exclude(pk=self.entry.pk).get()
        self.assertEqual(
            entry.opening_payments.get(mode_of_payment=self.cash_mode).opening_amount,
            Decimal("25000"),
        )
        # Bank mode wasn't in the POST — it was rendered with initial=0 and
        # the form coerced the blank to Decimal("0").
        self.assertEqual(
            entry.opening_payments.get(mode_of_payment=self.bank_mode).opening_amount,
            Decimal("0"),
        )

    def test_create_get_renders_all_active_modes(self):
        """On GET, the form shows one input per active ModeOfPayment."""
        response = self.client.get(reverse("staff:opening_entry_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'name="mop_{self.cash_mode.pk}"')
        self.assertContains(response, f'name="mop_{self.bank_mode.pk}"')
        # No inline formset management form (pre-change UI used one)
        self.assertNotContains(response, "opening_payments-TOTAL_FORMS")
        self.assertContains(response, "Opening Float")

    def test_create_post_blocks_when_no_modes_configured(self):
        """Re-render with error if no active ModeOfPayment exists."""
        ModeOfPayment.objects.update(enabled=False)
        response = self.client.post(reverse("staff:opening_entry_create"), data={})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No active payment methods")
        self.assertEqual(POSOpeningEntry.objects.count(), 1)

    def test_detail_200(self):
        response = self.client.get(reverse("staff:opening_entry_detail", kwargs={"pk": self.entry.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Cash")
        self.assertContains(response, "Opening Float")

    def test_detail_404(self):
        response = self.client.get(reverse("staff:opening_entry_detail", kwargs={"pk": 9999}))
        self.assertEqual(response.status_code, 404)

    def test_detail_get_renders_inline_form_for_draft(self):
        """For a DRAFT opening, the detail page renders the float table as
        an inline-editable form (POST back to the same detail URL)."""
        response = self.client.get(reverse("staff:opening_entry_detail", kwargs={"pk": self.entry.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'action="{reverse("staff:opening_entry_detail", kwargs={"pk": self.entry.pk})}"',
        )
        self.assertContains(response, "Submit & Open Shift")

    def test_detail_post_saves_amounts(self):
        """POST to the detail URL re-uses the create form to save the edited
        opening amounts (PRG)."""
        response = self.client.post(
            reverse("staff:opening_entry_detail", kwargs={"pk": self.entry.pk}),
            data={
                f"mop_{self.cash_mode.pk}": "99999",
                f"mop_{self.bank_mode.pk}": "0",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.entry.refresh_from_db()
        self.assertEqual(
            self.entry.opening_payments.get(mode_of_payment=self.cash_mode).opening_amount,
            Decimal("99999"),
        )

    def test_detail_post_blocked_when_submitted(self):
        """POST to a SUBMITTED opening's detail URL is rejected — the entry
        is immutable once the shift is open (ERPNext submit/cancel pattern)."""
        self.entry.submit()
        response = self.client.post(
            reverse("staff:opening_entry_detail", kwargs={"pk": self.entry.pk}),
            data={f"mop_{self.cash_mode.pk}": "1"},
        )
        self.assertEqual(response.status_code, 302)
        # Amount unchanged.
        self.entry.refresh_from_db()
        self.assertEqual(
            self.entry.opening_payments.get(mode_of_payment=self.cash_mode).opening_amount,
            Decimal("50000"),
        )

    def test_detail_get_read_only_when_submitted(self):
        """For an Open / Closed / Cancelled entry, the detail page renders
        the float table read-only — no inline form, no Save button."""
        self.entry.submit()
        response = self.client.get(reverse("staff:opening_entry_detail", kwargs={"pk": self.entry.pk}))
        self.assertEqual(response.status_code, 200)
        # The inline form's POST action does NOT appear when read-only.
        self.assertNotContains(
            response,
            f'action="{reverse("staff:opening_entry_detail", kwargs={"pk": self.entry.pk})}"',
        )

    def test_submit_post(self):
        response = self.client.post(reverse("staff:opening_entry_submit", kwargs={"pk": self.entry.pk}))
        self.assertRedirects(
            response,
            reverse("staff:opening_entry_detail", kwargs={"pk": self.entry.pk}),
        )
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, POSOpeningEntry.SUBMITTED)

    def test_submit_requires_post(self):
        response = self.client.get(reverse("staff:opening_entry_submit", kwargs={"pk": self.entry.pk}))
        self.assertEqual(response.status_code, 405)

    def test_cancel_post(self):
        response = self.client.post(reverse("staff:opening_entry_cancel", kwargs={"pk": self.entry.pk}))
        self.assertEqual(response.status_code, 302)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, POSOpeningEntry.CANCELLED)
        self.assertEqual(self.entry.cancelled_by, self.user)

    def test_cancel_requires_post(self):
        response = self.client.get(reverse("staff:opening_entry_cancel", kwargs={"pk": self.entry.pk}))
        self.assertEqual(response.status_code, 405)


class TestPOSClosingEntryViews(StaffViewTestBase):
    def setUp(self):
        super().setUp()
        # Open the shift so the closing entry is allowed
        self.entry.submit()

    def _seed_closing_draft(self):
        """Hit `closing_entry_create` (the real flow) to seed a DRAFT closing
        entry with one `ClosingPayment` per `OpeningPayment` row. Returns the
        new `POSClosingEntry` instance.
        """
        from apps.staff.models import POSClosingEntry

        response = self.client.post(reverse("staff:closing_entry_create"))
        # GET and POST both work — the view is method-agnostic.
        self.assertEqual(response.status_code, 302)
        return POSClosingEntry.objects.get(opening_entry=self.entry)

    def test_list_200(self):
        response = self.client.get(reverse("staff:closing_entry_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Closing Entries")

    def test_create_get_auto_creates_draft_and_seeds_rows(self):
        """GET to `closing_entry_create` immediately creates a DRAFT closing
        entry for the single open shift and seeds one ClosingPayment per
        OpeningPayment — no manual shift-selection step."""
        from apps.staff.models import POSClosingEntry

        response = self.client.get(reverse("staff:closing_entry_create"))
        self.assertEqual(response.status_code, 302)
        closing = POSClosingEntry.objects.get(opening_entry=self.entry)
        self.assertEqual(closing.status, POSClosingEntry.DRAFT)
        self.assertEqual(closing.cashier, self.user)
        # One closing row per opening row, all seeded with closing_amount=0.
        self.assertEqual(closing.closing_payments.count(), self.entry.opening_payments.count())
        for cp in closing.closing_payments.all():
            self.assertEqual(cp.closing_amount, Decimal("0"))
            self.assertEqual(cp.opening_amount, cp.expected_amount)

    def test_create_redirects_to_existing_draft(self):
        """A second 'Close Shift' click must NOT create a duplicate draft —
        it should redirect to the existing one (prevents double-click /
        refresh from creating duplicate drafts)."""
        from apps.staff.models import POSClosingEntry

        first = self._seed_closing_draft()
        response = self.client.get(reverse("staff:closing_entry_create"))
        self.assertRedirects(response, reverse("staff:closing_entry_detail", kwargs={"pk": first.pk}))
        self.assertEqual(POSClosingEntry.objects.filter(opening_entry=self.entry).count(), 1)

    def test_create_no_open_shift_redirects_to_dashboard(self):
        """If no shift is open, the create endpoint refuses to start a close
        and sends the user back to the dashboard with a warning."""
        from apps.staff.models import POSClosingEntry

        # Cancel the open shift first.
        self.entry.cancel(by_user=self.user)
        response = self.client.get(reverse("staff:closing_entry_create"))
        self.assertRedirects(response, reverse("staff:dashboard"))
        self.assertEqual(POSClosingEntry.objects.count(), 0)

    def test_detail_get_renders_inline_form_for_draft(self):
        """For a DRAFT closing, the detail page renders the reconciliation
        table as an inline-editable form (POST back to the same URL)."""
        closing = self._seed_closing_draft()
        response = self.client.get(reverse("staff:closing_entry_detail", kwargs={"pk": closing.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reconciliation")
        # The form posts back to the same detail URL, not a separate edit URL.
        self.assertContains(
            response,
            f'action="{reverse("staff:closing_entry_detail", kwargs={"pk": closing.pk})}"',
        )
        # Submit button is wired to the SweetAlert-confirmed submit form.
        self.assertContains(response, "Submit & Close Shift")

    def test_detail_post_saves_amounts(self):
        """POST to the detail URL saves the entered closing amounts (PRG)."""
        closing = self._seed_closing_draft()
        post_data = {}
        for cp in closing.closing_payments.all():
            post_data[f"cp_{cp.pk}-closing_amount"] = "49500.00"
        response = self.client.post(
            reverse("staff:closing_entry_detail", kwargs={"pk": closing.pk}),
            data=post_data,
        )
        self.assertRedirects(response, reverse("staff:closing_entry_detail", kwargs={"pk": closing.pk}))
        for cp in closing.closing_payments.all():
            cp.refresh_from_db()
            self.assertEqual(cp.closing_amount, Decimal("49500.00"))

    def test_detail_post_blocked_when_submitted(self):
        """POST to a SUBMITTED closing's detail URL is rejected — the entry
        is immutable once submitted (ERPNext submit/cancel pattern)."""
        closing = self._seed_closing_draft()
        for cp in closing.closing_payments.all():
            cp.closing_amount = cp.expected_amount
            cp.save(update_fields=["closing_amount"])
        submit_closing_entry(closing)
        post_data = {f"cp_{cp.pk}-closing_amount": "99999" for cp in closing.closing_payments.all()}
        response = self.client.post(
            reverse("staff:closing_entry_detail", kwargs={"pk": closing.pk}),
            data=post_data,
        )
        self.assertEqual(response.status_code, 302)
        # Amounts unchanged.
        for cp in closing.closing_payments.all():
            cp.refresh_from_db()
            self.assertEqual(cp.closing_amount, cp.expected_amount)

    def test_detail_get_read_only_when_submitted(self):
        """For a SUBMITTED closing, the detail page renders the table
        read-only — no inline form, no Save button."""
        closing = self._seed_closing_draft()
        submit_closing_entry(closing)
        response = self.client.get(reverse("staff:closing_entry_detail", kwargs={"pk": closing.pk}))
        self.assertEqual(response.status_code, 200)
        # The 'Difference' column only appears in the read-only view.
        self.assertContains(response, "Difference")
        # The inline form's POST action does NOT appear when read-only.
        self.assertNotContains(
            response,
            f'action="{reverse("staff:closing_entry_detail", kwargs={"pk": closing.pk})}"',
        )

    def test_submit_post(self):
        from apps.staff.models import POSClosingEntry

        closing = self._seed_closing_draft()
        for cp in closing.closing_payments.all():
            cp.closing_amount = cp.expected_amount  # exact match — no difference
            cp.save(update_fields=["closing_amount"])
        response = self.client.post(reverse("staff:closing_entry_submit", kwargs={"pk": closing.pk}))
        self.assertRedirects(
            response,
            reverse("staff:closing_entry_detail", kwargs={"pk": closing.pk}),
        )
        closing.refresh_from_db()
        self.assertEqual(closing.status, POSClosingEntry.SUBMITTED)
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_closed)

    def test_submit_requires_post(self):
        closing = self._seed_closing_draft()
        response = self.client.get(reverse("staff:closing_entry_submit", kwargs={"pk": closing.pk}))
        self.assertEqual(response.status_code, 405)

    def test_cancel_post(self):
        from apps.staff.models import POSClosingEntry

        closing = self._seed_closing_draft()
        for cp in closing.closing_payments.all():
            cp.closing_amount = cp.expected_amount
            cp.save(update_fields=["closing_amount"])
        submit_closing_entry(closing)
        response = self.client.post(reverse("staff:closing_entry_cancel", kwargs={"pk": closing.pk}))
        self.assertEqual(response.status_code, 302)
        closing.refresh_from_db()
        self.assertEqual(closing.status, POSClosingEntry.CANCELLED)

    def test_cancel_blocked_by_new_open_shift(self):
        from apps.staff.models import POSClosingEntry

        closing = self._seed_closing_draft()
        for cp in closing.closing_payments.all():
            cp.closing_amount = cp.expected_amount
            cp.save(update_fields=["closing_amount"])
        submit_closing_entry(closing)
        # Open a new shift — closing-cancellation must NOT reopen the older
        # shift when a newer one is already live.
        new_entry = POSOpeningEntry.objects.create(
            cashier=self.user,
            posting_date="2026-07-25",
        )
        OpeningPayment.objects.create(
            opening_entry=new_entry,
            mode_of_payment=self.cash_mode,
            opening_amount=Decimal("0"),
        )
        new_entry.submit()
        response = self.client.post(reverse("staff:closing_entry_cancel", kwargs={"pk": closing.pk}))
        self.assertEqual(response.status_code, 302)
        closing.refresh_from_db()
        self.assertEqual(closing.status, POSClosingEntry.SUBMITTED)

"""Model tests — account tree rules, fiscal years, GL immutability."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounting.models import FiscalYear, GLEntry, LedgerAccount


class LedgerAccountTreeTest(TestCase):
    def setUp(self):
        self.assets = LedgerAccount.objects.create(
            name="Assets", is_group=True, root_type=LedgerAccount.ASSET, report_type=LedgerAccount.BALANCE_SHEET
        )

    def test_root_requires_root_type(self):
        with self.assertRaises(ValidationError):
            LedgerAccount.objects.create(name="No Type", is_group=True)

    def test_child_inherits_root_type(self):
        child = LedgerAccount.objects.create(name="Cash", parent=self.assets)
        self.assertEqual(child.root_type, LedgerAccount.ASSET)

    def test_child_root_type_must_match_parent(self):
        with self.assertRaises(ValidationError):
            LedgerAccount.objects.create(name="Bad", parent=self.assets, root_type=LedgerAccount.INCOME)

    def test_parent_must_be_group(self):
        leaf = LedgerAccount.objects.create(name="Cash", parent=self.assets)
        with self.assertRaises(ValidationError):
            LedgerAccount.objects.create(name="Sub", parent=leaf)

    def test_no_self_parent(self):
        account = LedgerAccount.objects.create(name="Cash", parent=self.assets)
        account.parent = account
        with self.assertRaises(ValidationError):
            account.full_clean()

    def test_leaf_cannot_be_parent(self):
        # A leaf account can never gain children: the parent must be a group.
        leaf = LedgerAccount.objects.create(name="Cash", parent=self.assets)
        with self.assertRaises(ValidationError):
            LedgerAccount.objects.create(name="Sub", parent=leaf)

    def test_group_with_children_cannot_disable(self):
        child = LedgerAccount.objects.create(name="Cash", parent=self.assets)
        self.assets.disabled = True
        with self.assertRaises(ValidationError):
            self.assets.full_clean()
        child.delete()

    def test_delete_protected_when_children(self):
        LedgerAccount.objects.create(name="Cash", parent=self.assets)
        with self.assertRaises(ValidationError):
            self.assets.delete()

    def test_unique_name(self):
        LedgerAccount.objects.create(name="Cash", parent=self.assets)
        with self.assertRaises(ValidationError):
            LedgerAccount.objects.create(name="Cash", parent=self.assets)


class FiscalYearTest(TestCase):
    def test_end_after_start(self):
        with self.assertRaises(ValidationError):
            FiscalYear.objects.create(
                name="2026",
                year_start_date=date(2026, 1, 1),
                year_end_date=date(2025, 12, 31),
            )

    def test_overlap_rejected(self):
        FiscalYear.objects.create(name="2026", year_start_date=date(2026, 1, 1), year_end_date=date(2026, 12, 31))
        with self.assertRaises(ValidationError):
            FiscalYear.objects.create(name="2026B", year_start_date=date(2026, 6, 1), year_end_date=date(2027, 5, 31))

    def test_disabled_can_overlap(self):
        FiscalYear.objects.create(name="2026", year_start_date=date(2026, 1, 1), year_end_date=date(2026, 12, 31))
        FiscalYear.objects.create(
            name="2026C",
            year_start_date=date(2026, 1, 1),
            year_end_date=date(2026, 12, 31),
            disabled=True,
        )

    def test_get_for_returns_covering_year(self):
        year = FiscalYear.objects.create(
            name="2026", year_start_date=date(2026, 1, 1), year_end_date=date(2026, 12, 31)
        )
        self.assertEqual(FiscalYear.get_for(date(2026, 6, 15)), year)

    def test_get_for_missing_raises(self):
        with self.assertRaises(ValidationError):
            FiscalYear.get_for(date(2025, 6, 15))


class GLEntryImmutabilityTest(TestCase):
    def setUp(self):
        self.assets = LedgerAccount.objects.create(
            name="Assets", is_group=True, root_type=LedgerAccount.ASSET, report_type=LedgerAccount.BALANCE_SHEET
        )
        self.cash = LedgerAccount.objects.create(name="Cash", parent=self.assets)
        self.income = LedgerAccount.objects.create(
            name="Income", is_group=True, root_type=LedgerAccount.INCOME, report_type=LedgerAccount.PROFIT_AND_LOSS
        )
        self.sales = LedgerAccount.objects.create(name="Sales", parent=self.income)
        self.year = FiscalYear.objects.create(
            name="2026", year_start_date=date(2026, 1, 1), year_end_date=date(2026, 12, 31)
        )

    def test_post_creates_balanced_rows(self):
        entries = GLEntry.post(
            posting_date=date(2026, 5, 1),
            rows=[
                {"account": self.cash, "debit": Decimal("100")},
                {"account": self.sales, "credit": Decimal("100")},
            ],
            voucher_type="Order",
            voucher_no="X-1",
        )
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].fiscal_year, self.year)
        self.assertEqual(entries[0].debit, Decimal("100"))
        self.assertEqual(entries[1].credit, Decimal("100"))

    def test_post_outside_year_raises(self):
        with self.assertRaises(ValidationError):
            GLEntry.post(
                posting_date=date(2027, 1, 1),
                rows=[
                    {"account": self.cash, "debit": Decimal("100")},
                    {"account": self.sales, "credit": Decimal("100")},
                ],
                voucher_type="Order",
                voucher_no="X-2",
            )

    def test_cannot_edit_existing_entry(self):
        entry = GLEntry.post(
            posting_date=date(2026, 5, 1),
            rows=[
                {"account": self.cash, "debit": Decimal("100")},
                {"account": self.sales, "credit": Decimal("100")},
            ],
            voucher_type="Order",
            voucher_no="X-3",
        )[0]
        entry.debit = Decimal("200")
        with self.assertRaises(ValidationError):
            entry.save()

    def test_cannot_delete_entry(self):
        entry = GLEntry.post(
            posting_date=date(2026, 5, 1),
            rows=[
                {"account": self.cash, "debit": Decimal("100")},
                {"account": self.sales, "credit": Decimal("100")},
            ],
            voucher_type="Order",
            voucher_no="X-4",
        )[0]
        with self.assertRaises(ValidationError):
            entry.delete()

    def test_group_account_rejected(self):
        with self.assertRaises(ValidationError):
            GLEntry.post(
                posting_date=date(2026, 5, 1),
                rows=[
                    {"account": self.assets, "debit": Decimal("100")},
                    {"account": self.sales, "credit": Decimal("100")},
                ],
                voucher_type="Order",
                voucher_no="X-5",
            )

    def test_frozen_and_disabled_rejected(self):
        frozen = LedgerAccount.objects.create(name="Frozen", parent=self.assets, freeze_account=True)
        disabled = LedgerAccount.objects.create(name="Disabled", parent=self.assets, disabled=True)
        with self.assertRaises(ValidationError):
            GLEntry.post(
                posting_date=date(2026, 5, 1),
                rows=[
                    {"account": frozen, "debit": Decimal("100")},
                    {"account": self.sales, "credit": Decimal("100")},
                ],
                voucher_type="Order",
                voucher_no="X-6",
            )
        with self.assertRaises(ValidationError):
            GLEntry.post(
                posting_date=date(2026, 5, 1),
                rows=[
                    {"account": disabled, "debit": Decimal("100")},
                    {"account": self.sales, "credit": Decimal("100")},
                ],
                voucher_type="Order",
                voucher_no="X-7",
            )

    def test_reversal_flag_can_be_flipped(self):
        entry = GLEntry.post(
            posting_date=date(2026, 5, 1),
            rows=[
                {"account": self.cash, "debit": Decimal("100")},
                {"account": self.sales, "credit": Decimal("100")},
            ],
            voucher_type="Order",
            voucher_no="X-8",
        )[0]
        entry.is_cancelled = True
        entry.save(update_fields=["is_cancelled", "updated_at"])
        entry.refresh_from_db()
        self.assertTrue(entry.is_cancelled)
        entry.is_cancelled = False
        with self.assertRaises(ValidationError):
            entry.save()

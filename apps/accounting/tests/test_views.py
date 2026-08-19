"""View tests — backoffice gate and CRUD flows for accounting pages."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounting.models import CostCenter, FiscalYear, JournalEntry, JournalEntryAccount, LedgerAccount
from apps.users.models import CustomUser


class AccountingViewTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(username="admin", password="x", is_superuser=True)
        cls.cashier = CustomUser.objects.create_user(username="cashier", password="x")
        cls.assets = LedgerAccount.objects.create(
            name="Assets", is_group=True, root_type=LedgerAccount.ASSET, report_type=LedgerAccount.BALANCE_SHEET
        )
        cls.cash = LedgerAccount.objects.create(name="Cash", parent=cls.assets)
        cls.income = LedgerAccount.objects.create(
            name="Income", is_group=True, root_type=LedgerAccount.INCOME, report_type=LedgerAccount.PROFIT_AND_LOSS
        )
        cls.sales = LedgerAccount.objects.create(name="Sales", parent=cls.income)
        cls.year = FiscalYear.objects.create(
            name="2026", year_start_date=date(2026, 1, 1), year_end_date=date(2026, 12, 31)
        )
        cls.cc = CostCenter.objects.create(name="Kitchen")


class AccountingViewAccessTest(AccountingViewTestBase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("accounting:dashboard"))
        self.assertNotEqual(response.status_code, 200)

    def test_cashier_cannot_access(self):
        self.client.force_login(self.cashier)
        # The backoffice middleware redirects cashiers to home.
        response = self.client.get(reverse("accounting:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_admin_can_access_all_pages(self):
        self.client.force_login(self.admin)
        for url in [
            "accounting:dashboard",
            "accounting:chart_of_accounts",
            "accounting:journal_entry_list",
            "accounting:gl_entry_list",
            "accounting:fiscal_year_list",
            "accounting:cost_center_list",
        ]:
            response = self.client.get(reverse(url))
            self.assertEqual(response.status_code, 200, url)


class ChartOfAccountsViewTest(AccountingViewTestBase):
    def test_account_create(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounting:account_create"),
            {
                "name": "Bank",
                "parent": self.assets.pk,
                "is_group": "on",
                "root_type": "ASSET",
                "report_type": "BALANCE_SHEET",
            },
        )
        self.assertRedirects(response, reverse("accounting:chart_of_accounts"))
        self.assertTrue(LedgerAccount.objects.filter(name="Bank").exists())

    def test_account_detail_shows_children(self):
        self.client.force_login(self.admin)
        child = LedgerAccount.objects.create(name="Cash2", parent=self.assets)
        response = self.client.get(reverse("accounting:account_detail", args=[self.assets.pk]))
        self.assertContains(response, child.name)

    def test_chart_shows_nested_leaves(self):
        self.client.force_login(self.admin)
        bank = LedgerAccount.objects.create(name="Bank Accounts", parent=self.assets, is_group=True)
        leaf = LedgerAccount.objects.create(name="Electronic Account", parent=bank)
        response = self.client.get(reverse("accounting:chart_of_accounts"))
        self.assertContains(response, bank.name)
        self.assertContains(response, leaf.name)


class JournalEntryViewTest(AccountingViewTestBase):
    def test_create_journal_entry(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounting:journal_entry_create"),
            {
                "voucher_type": JournalEntry.JOURNAL,
                "posting_date": "2026-05-01",
                "remark": "Test",
                "accounts-TOTAL_FORMS": "2",
                "accounts-INITIAL_FORMS": "0",
                "accounts-MIN_NUM_FORMS": "1",
                "accounts-MAX_NUM_FORMS": "1000",
                "accounts-0-account": self.cash.pk,
                "accounts-0-debit": "100.00",
                "accounts-0-credit": "",
                "accounts-1-account": self.sales.pk,
                "accounts-1-debit": "",
                "accounts-1-credit": "100.00",
            },
        )
        journal = JournalEntry.objects.first()
        self.assertIsNotNone(journal)
        self.assertRedirects(response, reverse("accounting:journal_entry_detail", args=[journal.pk]))
        self.assertEqual(journal.accounts.count(), 2)

    def test_submit_journal_entry(self):
        self.client.force_login(self.admin)
        journal = JournalEntry.objects.create(voucher_type=JournalEntry.JOURNAL, posting_date=date(2026, 5, 1))
        JournalEntryAccount.objects.create(journal_entry=journal, account=self.cash, debit=Decimal("100"))
        JournalEntryAccount.objects.create(journal_entry=journal, account=self.sales, credit=Decimal("100"))
        response = self.client.post(reverse("accounting:journal_entry_submit", args=[journal.pk]))
        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalEntry.SUBMITTED)
        self.assertRedirects(response, reverse("accounting:journal_entry_detail", args=[journal.pk]))

    def test_opening_submit_requires_review_confirmation(self):
        self.client.force_login(self.admin)
        journal = JournalEntry.objects.create(voucher_type=JournalEntry.OPENING, posting_date=date(2026, 5, 1))
        JournalEntryAccount.objects.create(
            journal_entry=journal, account=self.cash, debit=Decimal("100"), remarks="Cash count"
        )
        JournalEntryAccount.objects.create(
            journal_entry=journal, account=self.sales, credit=Decimal("100"), remarks="Equity"
        )
        response = self.client.post(reverse("accounting:journal_entry_submit", args=[journal.pk]))
        self.assertRedirects(response, reverse("accounting:journal_entry_review", args=[journal.pk]))
        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalEntry.DRAFT)

        review = self.client.get(reverse("accounting:journal_entry_review", args=[journal.pk]))
        self.assertEqual(review.status_code, 200)
        self.assertContains(review, "Confirm submit")

        response = self.client.post(reverse("accounting:journal_entry_submit", args=[journal.pk]), {"confirmed": "1"})
        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalEntry.SUBMITTED)
        self.assertRedirects(response, reverse("accounting:journal_entry_detail", args=[journal.pk]))

    def test_create_journal_entry_rejects_empty_formset(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounting:journal_entry_create"),
            {
                "voucher_type": JournalEntry.JOURNAL,
                "posting_date": "2026-05-01",
                "remark": "No rows",
                "accounts-TOTAL_FORMS": "0",
                "accounts-INITIAL_FORMS": "0",
                "accounts-MIN_NUM_FORMS": "1",
                "accounts-MAX_NUM_FORMS": "1000",
            },
        )
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertContains(response, "at least 1 form")

    def test_journal_entry_account_add_returns_partial(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounting:journal_entry_account_add"),
            {
                "voucher_type": JournalEntry.JOURNAL,
                "posting_date": "2026-05-01",
                "accounts-TOTAL_FORMS": "2",
                "accounts-INITIAL_FORMS": "0",
                "accounts-MIN_NUM_FORMS": "1",
                "accounts-MAX_NUM_FORMS": "1000",
                "accounts-0-account": self.cash.pk,
                "accounts-0-debit": "100.00",
                "accounts-0-credit": "",
                "accounts-1-account": self.sales.pk,
                "accounts-1-debit": "",
                "accounts-1-credit": "100.00",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "accounts-TOTAL_FORMS")
        self.assertContains(response, 'name="accounts-2-account"')

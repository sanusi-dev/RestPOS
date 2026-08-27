"""Supplier payables tests — models, GL posting, outstanding, and cancellation."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounting.models import GLEntry, LedgerAccount
from apps.accounting.payables_models import (
    Supplier,
    SupplierInvoice,
    SupplierInvoiceItem,
    SupplierPayment,
    SupplierPaymentAllocation,
)
from apps.inventory.models import UOM, Item, ItemGroup, PurchaseReceipt, PurchaseReceiptItem, Warehouse
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import Restaurant

from .helpers import setup_chart_of_accounts


class PayablesTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.store = Warehouse.objects.create(name="Store Payables")
        cls.restaurant = Restaurant.objects.create(company="Test Co", store_warehouse=cls.store)
        cls.accounts = setup_chart_of_accounts(cls.restaurant)
        # Refresh store to get account wired by helper
        cls.store.refresh_from_db()
        if not cls.store.account_id:
            cls.store.account = cls.accounts["stock_in_hand"]
            cls.store.save(update_fields=["account", "updated_at"])
            cls.store.refresh_from_db()
        cls.group = ItemGroup.objects.create(name=f"Supplies {cls.restaurant.pk}")
        # Ensure group name unique; helper already created fiscal year etc.
        cls.item = Item.objects.create(
            item_name="Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_stock_item=True,
            is_purchase_item=True,
        )
        cls.supplier = Supplier.objects.create(supplier_name=f"Mama Bisi Foods {cls.restaurant.pk}")
        cls.cash, _ = ModeOfPayment.objects.get_or_create(name="Cash", defaults={"type": "CASH"})
        PaymentGLMapping.objects.get_or_create(
            mode_of_payment=cls.cash, defaults={"default_account": cls.accounts["cash"]}
        )
        cls.expense_account = LedgerAccount.objects.create(
            name=f"Cleaning Expense {cls.restaurant.pk}",
            parent=cls.accounts["expenses"],
            root_type=LedgerAccount.EXPENSE,
            report_type=LedgerAccount.PROFIT_AND_LOSS,
        )

    def _make_invoice(self, supplier=None, **kwargs):
        defaults = {"supplier": supplier or self.supplier, "posting_date": date.today()}
        defaults.update(kwargs)
        return SupplierInvoice.objects.create(**defaults)

    def _add_stock_line(self, invoice, item=None, qty=2, rate=100):
        return SupplierInvoiceItem.objects.create(invoice=invoice, item=item or self.item, qty=qty, rate=rate)

    def _add_expense_line(self, invoice, amount=500):
        return SupplierInvoiceItem.objects.create(
            invoice=invoice, expense_account=self.expense_account, qty=1, rate=amount
        )


class SupplierModelTest(PayablesTestBase):
    def test_default_flag_is_singleton(self):
        other = Supplier.objects.create(supplier_name="Other", is_default=True)
        self.supplier.refresh_from_db()
        self.assertTrue(other.is_default)
        self.assertFalse(self.supplier.is_default)

    def test_payable_account_requires_leaf(self):
        with self.assertRaises(ValidationError):
            Supplier.objects.create(supplier_name="Bad", payable_account=self.accounts["assets"])

    def test_disabled_supplier_can_hold_history(self):
        self.supplier.disabled = True
        self.supplier.save()
        # Stock invoice needs receipt link
        receipt = PurchaseReceipt.objects.create(
            supplier=self.supplier,
            supplier_name=self.supplier.supplier_name,
            warehouse=self.store,
            posting_date=date.today(),
        )
        receipt_line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt, item=self.item, received_qty=2, rate=100
        )
        from apps.inventory.services import submit_purchase_receipt

        submit_purchase_receipt(receipt)
        invoice = self._make_invoice(purchase_receipt=receipt)
        SupplierInvoiceItem.objects.create(
            invoice=invoice, item=self.item, qty=2, rate=100, source_receipt_line=receipt_line
        )
        invoice.submit()
        self.assertEqual(invoice.status, SupplierInvoice.SUBMITTED)


class SupplierInvoiceSubmitTest(PayablesTestBase):
    def test_submit_posts_stock_and_payable_legs(self):
        # Stock invoice must link to a purchase receipt — posts Dr GRNI / Cr Payable
        receipt = PurchaseReceipt.objects.create(
            supplier=self.supplier,
            supplier_name=self.supplier.supplier_name,
            warehouse=self.store,
            posting_date=date.today(),
        )
        receipt_line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt, item=self.item, received_qty=2, rate=100
        )
        from apps.inventory.services import submit_purchase_receipt

        submit_purchase_receipt(receipt)
        invoice = self._make_invoice(purchase_receipt=receipt)
        # Stock line linked to receipt line must match qty/rate
        SupplierInvoiceItem.objects.create(
            invoice=invoice, item=self.item, qty=2, rate=100, source_receipt_line=receipt_line
        )
        invoice.submit()
        invoice.refresh_from_db()

        self.assertEqual(invoice.status, SupplierInvoice.SUBMITTED)
        self.assertEqual(invoice.total, Decimal("200"))
        self.assertEqual(invoice.outstanding_amount, Decimal("200"))
        entries = GLEntry.objects.filter(voucher_type="Supplier Invoice", voucher_no=invoice.invoice_number)
        self.assertEqual(entries.count(), 2)
        from apps.settings.models import Restaurant

        grni_acct = Restaurant.objects.get(pk=self.restaurant.pk).stock_received_but_not_billed_account
        stock = entries.get(account=grni_acct)
        self.assertEqual(stock.debit, Decimal("200"))
        payable = entries.get(account=self.accounts["payable"])
        self.assertEqual(payable.credit, Decimal("200"))

    def test_submit_posts_expense_and_payable_legs(self):
        invoice = self._make_invoice()
        self._add_expense_line(invoice, amount=500)
        invoice.submit()
        entries = GLEntry.objects.filter(voucher_type="Supplier Invoice", voucher_no=invoice.invoice_number)
        expense = entries.get(account=self.expense_account)
        self.assertEqual(expense.debit, Decimal("500"))
        payable = entries.get(account=self.accounts["payable"])
        self.assertEqual(payable.credit, Decimal("500"))

    def test_submit_with_no_lines_rejected(self):
        invoice = self._make_invoice()
        with self.assertRaisesMessage(ValidationError, "Add at least one line"):
            invoice.submit()
        self.assertEqual(invoice.status, SupplierInvoice.DRAFT)

    def test_submit_fails_closed_without_payable_account(self):
        self.restaurant.default_payable_account = None
        self.restaurant.save()
        receipt = PurchaseReceipt.objects.create(
            supplier=self.supplier,
            supplier_name=self.supplier.supplier_name,
            warehouse=self.store,
            posting_date=date.today(),
        )
        receipt_line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt, item=self.item, received_qty=2, rate=100
        )
        from apps.inventory.services import submit_purchase_receipt

        submit_purchase_receipt(receipt)
        invoice = self._make_invoice(purchase_receipt=receipt)
        SupplierInvoiceItem.objects.create(
            invoice=invoice, item=self.item, qty=2, rate=100, source_receipt_line=receipt_line
        )
        with self.assertRaisesMessage(ValidationError, "default payable account"):
            invoice.submit()
        self.assertEqual(invoice.status, SupplierInvoice.DRAFT)

    def test_submit_uses_supplier_payable_override(self):
        override = LedgerAccount.objects.create(
            name="Special Payable",
            parent=self.accounts["liabilities"],
            root_type=LedgerAccount.LIABILITY,
            report_type=LedgerAccount.BALANCE_SHEET,
        )
        self.supplier.payable_account = override
        self.supplier.save()
        receipt = PurchaseReceipt.objects.create(
            supplier=self.supplier,
            supplier_name=self.supplier.supplier_name,
            warehouse=self.store,
            posting_date=date.today(),
        )
        receipt_line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt, item=self.item, received_qty=2, rate=100
        )
        from apps.inventory.services import submit_purchase_receipt

        submit_purchase_receipt(receipt)
        invoice = self._make_invoice(purchase_receipt=receipt)
        SupplierInvoiceItem.objects.create(
            invoice=invoice, item=self.item, qty=2, rate=100, source_receipt_line=receipt_line
        )
        invoice.submit()
        entries = GLEntry.objects.filter(voucher_type="Supplier Invoice", voucher_no=invoice.invoice_number)
        self.assertTrue(entries.filter(account=override).exists())

    def test_submit_uses_receipt_line_source(self):
        receipt = PurchaseReceipt.objects.create(
            supplier=self.supplier, supplier_name="Mama Bisi Foods", posting_date=date.today(), warehouse=self.store
        )
        from apps.inventory.services import submit_purchase_receipt

        receipt_line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt, item=self.item, received_qty=5, rate=80
        )
        submit_purchase_receipt(receipt)

        invoice = self._make_invoice()
        line = SupplierInvoiceItem.objects.create(
            invoice=invoice, source_receipt_line=receipt_line, qty=Decimal("5"), rate=Decimal("80")
        )
        line.refresh_from_db()
        self.assertEqual(line.qty, Decimal("5"))
        self.assertEqual(line.rate, Decimal("80"))
        self.assertEqual(line.amount, Decimal("400"))

    def test_stock_line_on_receipt_invoice_requires_receipt_link(self):
        receipt = PurchaseReceipt.objects.create(
            supplier=self.supplier,
            supplier_name="Mama Bisi Foods",
            posting_date=date.today(),
            warehouse=self.store,
        )
        PurchaseReceiptItem.objects.create(purchase_receipt=receipt, item=self.item, received_qty=2, rate=100)
        from apps.inventory.services import submit_purchase_receipt

        submit_purchase_receipt(receipt)
        invoice = self._make_invoice(purchase_receipt=receipt)
        # A stock line without the receipt link is rejected — it could not
        # clear GRNI at the receipt rate.
        with self.assertRaisesMessage(ValidationError, "must link to a receipt line"):
            SupplierInvoiceItem.objects.create(invoice=invoice, item=self.item, qty=2, rate=100)
        # The same guard blocks submit even if the line bypassed clean().
        line = SupplierInvoiceItem(invoice=invoice, item=self.item, qty=2, rate=100)
        with self.assertRaisesMessage(ValidationError, "must link to a receipt line"):
            line.validate_for_submission()

    def test_stock_line_autofills_qty_rate_from_receipt_line(self):
        receipt = PurchaseReceipt.objects.create(
            supplier=self.supplier,
            supplier_name="Mama Bisi Foods",
            posting_date=date.today(),
            warehouse=self.store,
        )
        receipt_line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt, item=self.item, received_qty=5, rate=80
        )
        from apps.inventory.services import submit_purchase_receipt

        submit_purchase_receipt(receipt)
        invoice = self._make_invoice(purchase_receipt=receipt)
        line = SupplierInvoiceItem.objects.create(invoice=invoice, source_receipt_line=receipt_line)
        line.refresh_from_db()
        self.assertEqual(line.item, self.item)
        self.assertEqual(line.qty, Decimal("5"))
        self.assertEqual(line.rate, Decimal("80"))
        self.assertEqual(line.amount, Decimal("400"))

    def test_cancel_reverses_gl_and_clears_outstanding(self):
        receipt = PurchaseReceipt.objects.create(
            supplier=self.supplier,
            supplier_name=self.supplier.supplier_name,
            warehouse=self.store,
            posting_date=date.today(),
        )
        receipt_line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt, item=self.item, received_qty=2, rate=100
        )
        from apps.inventory.services import submit_purchase_receipt

        submit_purchase_receipt(receipt)
        invoice = self._make_invoice(purchase_receipt=receipt)
        SupplierInvoiceItem.objects.create(
            invoice=invoice, item=self.item, qty=2, rate=100, source_receipt_line=receipt_line
        )
        invoice.submit()
        invoice.cancel()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, SupplierInvoice.CANCELLED)
        self.assertEqual(invoice.outstanding_amount, Decimal("0"))
        originals = GLEntry.objects.filter(
            voucher_type="Supplier Invoice", voucher_no=invoice.invoice_number, is_cancelled=True
        )
        self.assertEqual(originals.count(), 2)
        reversals = GLEntry.objects.filter(
            voucher_type="Supplier Invoice", voucher_no=invoice.invoice_number, is_cancelled=False, remarks="Reversal"
        )
        self.assertEqual(reversals.count(), 2)
        # Reversal mirrors: GRNI credited, payable debited.
        self.assertEqual(reversals.get(account=self.accounts["grni"]).credit, Decimal("200"))
        self.assertEqual(reversals.get(account=self.accounts["payable"]).debit, Decimal("200"))

    def test_cancel_twice_is_idempotent(self):
        receipt = PurchaseReceipt.objects.create(
            supplier=self.supplier,
            supplier_name=self.supplier.supplier_name,
            warehouse=self.store,
            posting_date=date.today(),
        )
        receipt_line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt, item=self.item, received_qty=2, rate=100
        )
        from apps.inventory.services import submit_purchase_receipt

        submit_purchase_receipt(receipt)
        invoice = self._make_invoice(purchase_receipt=receipt)
        SupplierInvoiceItem.objects.create(
            invoice=invoice, item=self.item, qty=2, rate=100, source_receipt_line=receipt_line
        )
        invoice.submit()
        invoice.cancel()
        invoice.cancel()
        self.assertEqual(invoice.status, SupplierInvoice.CANCELLED)

    def test_cancel_posts_reversal_on_invoice_posting_date(self):
        receipt = PurchaseReceipt.objects.create(
            supplier=self.supplier,
            supplier_name=self.supplier.supplier_name,
            warehouse=self.store,
            posting_date=date(2026, 8, 1),
        )
        receipt_line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt, item=self.item, received_qty=2, rate=100
        )
        from apps.inventory.services import submit_purchase_receipt

        submit_purchase_receipt(receipt)
        invoice = self._make_invoice(purchase_receipt=receipt, posting_date=date(2026, 8, 1))
        SupplierInvoiceItem.objects.create(
            invoice=invoice, item=self.item, qty=2, rate=100, source_receipt_line=receipt_line
        )
        invoice.submit()
        invoice.cancel()
        reversals = GLEntry.objects.filter(
            voucher_type="Supplier Invoice",
            voucher_no=invoice.invoice_number,
            is_cancelled=False,
            remarks="Reversal",
        )
        self.assertEqual(reversals.count(), 2)
        self.assertTrue(all(gl.posting_date == date(2026, 8, 1) for gl in reversals))


class SupplierPaymentTest(PayablesTestBase):
    def _paid_invoice(self, amount=200):
        # qty 2 × rate amount — create receipt-linked stock invoice
        receipt = PurchaseReceipt.objects.create(
            supplier=self.supplier,
            supplier_name=self.supplier.supplier_name,
            warehouse=self.store,
            posting_date=date.today(),
        )
        receipt_line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt, item=self.item, received_qty=2, rate=amount
        )
        from apps.inventory.services import submit_purchase_receipt

        submit_purchase_receipt(receipt)
        invoice = self._make_invoice(purchase_receipt=receipt)
        SupplierInvoiceItem.objects.create(
            invoice=invoice, item=self.item, qty=2, rate=amount, source_receipt_line=receipt_line
        )
        invoice.submit()
        return invoice

    def _make_payment(self, invoice, amount):
        payment = SupplierPayment.objects.create(supplier=self.supplier, paid_amount=amount, mode_of_payment=self.cash)
        SupplierPaymentAllocation.objects.create(payment=payment, invoice=invoice, allocated_amount=amount)
        return payment

    def test_submit_posts_payable_and_cash_legs_and_reduces_outstanding(self):
        invoice = self._paid_invoice(amount=100)  # total 200
        payment = self._make_payment(invoice, Decimal("200"))
        payment.submit()
        payment.refresh_from_db()
        invoice.refresh_from_db()

        self.assertEqual(payment.status, SupplierPayment.SUBMITTED)
        self.assertEqual(invoice.outstanding_amount, Decimal("0"))
        self.assertEqual(invoice.payment_status, "Paid")
        entries = GLEntry.objects.filter(voucher_type="Supplier Payment", voucher_no=payment.payment_number)
        self.assertEqual(entries.count(), 2)
        self.assertEqual(entries.get(account=self.accounts["payable"]).debit, Decimal("200"))
        self.assertEqual(entries.get(account=self.accounts["cash"]).credit, Decimal("200"))

    def test_partial_payment_leaves_partly_paid(self):
        invoice = self._paid_invoice(amount=200)  # total 400
        payment = self._make_payment(invoice, Decimal("150"))
        payment.submit()
        invoice.refresh_from_db()
        self.assertEqual(invoice.outstanding_amount, Decimal("250"))
        self.assertEqual(invoice.payment_status, "Partly Paid")

    def test_payment_total_must_equal_allocations(self):
        invoice = self._paid_invoice(amount=200)  # total 400
        payment = SupplierPayment.objects.create(
            supplier=self.supplier, paid_amount=Decimal("500"), mode_of_payment=self.cash
        )
        SupplierPaymentAllocation.objects.create(payment=payment, invoice=invoice, allocated_amount=Decimal("400"))
        with self.assertRaisesMessage(ValidationError, "must equal the paid amount"):
            payment.submit()
        self.assertEqual(payment.status, SupplierPayment.DRAFT)

    def test_allocation_cannot_exceed_outstanding(self):
        invoice = self._paid_invoice(amount=200)  # qty 2 × rate 200 = 400 outstanding
        payment = SupplierPayment.objects.create(
            supplier=self.supplier, paid_amount=Decimal("500"), mode_of_payment=self.cash
        )
        with self.assertRaises(ValidationError):
            SupplierPaymentAllocation.objects.create(payment=payment, invoice=invoice, allocated_amount=Decimal("500"))

    def test_cancel_restores_outstanding_and_reverses_gl(self):
        invoice = self._paid_invoice(amount=100)  # total 200
        payment = self._make_payment(invoice, Decimal("200"))
        payment.submit()
        payment.cancel()
        invoice.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(payment.status, SupplierPayment.CANCELLED)
        self.assertEqual(invoice.outstanding_amount, Decimal("200"))
        originals = GLEntry.objects.filter(
            voucher_type="Supplier Payment", voucher_no=payment.payment_number, is_cancelled=True
        )
        self.assertEqual(originals.count(), 2)
        reversals = GLEntry.objects.filter(
            voucher_type="Supplier Payment", voucher_no=payment.payment_number, is_cancelled=False, remarks="Reversal"
        )
        self.assertEqual(reversals.get(account=self.accounts["payable"]).credit, Decimal("200"))
        self.assertEqual(reversals.get(account=self.accounts["cash"]).debit, Decimal("200"))

    def test_supplier_outstanding_balance_reflects_invoices_minus_payments(self):
        # qty 2 × rate → invoice totals are 600 and 200.
        invoice1 = self._paid_invoice(amount=300)
        self._paid_invoice(amount=100)
        self.assertEqual(self.supplier.outstanding_balance, Decimal("800"))
        payment = self._make_payment(invoice1, Decimal("200"))
        payment.submit()
        self.assertEqual(self.supplier.outstanding_balance, Decimal("600"))


class SupplierViewTest(PayablesTestBase):
    def test_cashier_cannot_access_suppliers(self):
        from django.test import Client

        client = Client()
        from apps.users.models import CustomUser

        cashier = CustomUser.objects.create_user(username="cashier", password="x")
        client.force_login(cashier)
        from django.urls import reverse

        response = client.get(reverse("accounting:supplier_list"))
        self.assertNotEqual(response.status_code, 200)

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import (
    UOM,
    Bin,
    Item,
    ItemGroup,
    PurchaseReceipt,
    PurchaseReceiptItem,
    StockLedgerEntry,
    Warehouse,
)


class PurchaseReceiptTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.accepted_wh = Warehouse.objects.create(name="Main Store")
        cls.item = Item.objects.create(
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
        )


class PurchaseReceiptCRUDTest(PurchaseReceiptTestBase):
    def test_create(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        self.assertEqual(receipt.supplier_name, "ABC Suppliers")
        self.assertEqual(receipt.status, "DRAFT")
        self.assertEqual(receipt.total, Decimal("0"))

    def test_str(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        self.assertIn("ABC Suppliers", str(receipt))
        self.assertIn("PR", str(receipt))

    def test_create_item(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rate=Decimal("100"),
        )
        self.assertIn(line, receipt.items.all())
        self.assertIn("x10", str(line))

    def test_clean_requires_warehouse(self):
        receipt = PurchaseReceipt(supplier_name="ABC Suppliers", warehouse=None)
        with self.assertRaises(ValidationError):
            receipt.full_clean()


class PurchaseReceiptItemAutoCalcTest(PurchaseReceiptTestBase):
    def test_amount_auto_calc(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rate=Decimal("150"),
        )
        self.assertEqual(line.amount, Decimal("1500"))


class PurchaseReceiptSubmitTest(PurchaseReceiptTestBase):
    def test_submit_creates_sles_to_warehouse(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rate=Decimal("100"),
        )
        receipt.submit()
        self.assertEqual(receipt.status, "SUBMITTED")
        sles = StockLedgerEntry.objects.filter(voucher_type="Purchase Receipt", voucher_no=str(receipt.pk))
        self.assertEqual(sles.count(), 1)
        self.assertEqual(sles[0].actual_qty, Decimal("10"))
        self.assertEqual(sles[0].warehouse, self.accepted_wh)
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.accepted_wh)
        self.assertEqual(bin_obj.actual_qty, Decimal("10"))

    def test_submit_sets_total(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rate=Decimal("100"),
        )
        receipt.submit()
        receipt.refresh_from_db()
        self.assertEqual(receipt.total, Decimal("1000"))

    def test_submit_only_on_draft(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        receipt.submit()
        receipt.submit()
        self.assertEqual(receipt.status, "SUBMITTED")

    def test_submitted_stock_visible_in_bin(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("12"),
            rate=Decimal("50"),
        )
        receipt.submit()
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.accepted_wh)
        self.assertEqual(bin_obj.actual_qty, Decimal("12"))
        self.assertGreater(bin_obj.valuation_rate, Decimal("0"))


class PurchaseReceiptCancelTest(PurchaseReceiptTestBase):
    def test_cancel_reverses_sles(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rate=Decimal("100"),
        )
        receipt.submit()
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.accepted_wh)
        self.assertEqual(bin_obj.actual_qty, Decimal("10"))

        receipt.cancel()
        self.assertEqual(receipt.status, "CANCELLED")
        bin_obj.refresh_from_db()
        self.assertEqual(bin_obj.actual_qty, Decimal("0"))

    def test_cancel_creates_reversal_entries(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rate=Decimal("100"),
        )
        receipt.submit()
        receipt.cancel()
        reversal_sles = StockLedgerEntry.objects.filter(
            voucher_type="Purchase Receipt Cancellation", voucher_no=str(receipt.pk)
        )
        self.assertEqual(reversal_sles.count(), 1)
        self.assertEqual(reversal_sles[0].actual_qty, Decimal("-10"))

    def test_cancel_only_on_submitted(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        receipt.cancel()
        self.assertEqual(receipt.status, "DRAFT")


class PurchaseReceiptStatusTransitionTest(PurchaseReceiptTestBase):
    def test_draft_to_submitted_to_cancelled(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.accepted_wh,
        )
        self.assertEqual(receipt.status, "DRAFT")
        receipt.submit()
        self.assertEqual(receipt.status, "SUBMITTED")
        receipt.cancel()
        self.assertEqual(receipt.status, "CANCELLED")

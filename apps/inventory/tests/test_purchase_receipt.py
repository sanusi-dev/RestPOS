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
from apps.settings.models import Branch


class PurchaseReceiptTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.accepted_wh = Warehouse.objects.create(name="Main Store", branch=cls.branch)
        cls.rejected_wh = Warehouse.objects.create(name="Rejected Store", branch=cls.branch, is_rejected=True)
        cls.item = Item.objects.create(
            item_code="RICE001",
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
        )


class PurchaseReceiptCRUDTest(PurchaseReceiptTestBase):
    def test_create(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        self.assertEqual(receipt.supplier_name, "ABC Suppliers")
        self.assertEqual(receipt.status, "DRAFT")
        self.assertEqual(receipt.total, Decimal("0"))

    def test_str(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        self.assertIn("ABC Suppliers", str(receipt))
        self.assertIn("PR", str(receipt))

    def test_create_item(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            uom=self.uom,
            rate=Decimal("100"),
        )
        self.assertIn(line, receipt.items.all())
        self.assertEqual(str(line), "RICE001 x10")

    def test_clean_requires_accepted_warehouse(self):
        receipt = PurchaseReceipt(supplier_name="ABC Suppliers", accepted_warehouse=None)
        with self.assertRaises(ValidationError):
            receipt.full_clean()


class PurchaseReceiptItemAutoCalcTest(PurchaseReceiptTestBase):
    def test_accepted_qty_auto_calc(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rejected_qty=Decimal("3"),
            uom=self.uom,
            rate=Decimal("100"),
        )
        self.assertEqual(line.accepted_qty, Decimal("7"))

    def test_accepted_qty_no_rejections(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            uom=self.uom,
            rate=Decimal("100"),
        )
        self.assertEqual(line.accepted_qty, Decimal("10"))

    def test_amount_auto_calc(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            uom=self.uom,
            rate=Decimal("150"),
        )
        self.assertEqual(line.amount, Decimal("1500"))

    def test_amount_includes_received_qty(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        line = PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rejected_qty=Decimal("3"),
            uom=self.uom,
            rate=Decimal("100"),
        )
        # amount = received_qty * rate (not accepted_qty * rate)
        self.assertEqual(line.amount, Decimal("1000"))

    def test_rejected_qty_cannot_exceed_received_qty(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        line = PurchaseReceiptItem(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("5"),
            rejected_qty=Decimal("8"),
            uom=self.uom,
            rate=Decimal("100"),
        )
        with self.assertRaises(ValidationError):
            line.full_clean()


class PurchaseReceiptSubmitTest(PurchaseReceiptTestBase):
    def test_submit_creates_sles_to_accepted_warehouse(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            uom=self.uom,
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
            accepted_warehouse=self.accepted_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            uom=self.uom,
            rate=Decimal("100"),
        )
        receipt.submit()
        receipt.refresh_from_db()
        self.assertEqual(receipt.total, Decimal("1000"))

    def test_submit_with_rejected_qty_creates_sle_to_rejected_warehouse(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
            rejected_warehouse=self.rejected_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rejected_qty=Decimal("3"),
            uom=self.uom,
            rate=Decimal("100"),
        )
        receipt.submit()
        sles = StockLedgerEntry.objects.filter(voucher_type="Purchase Receipt", voucher_no=str(receipt.pk))
        self.assertEqual(sles.count(), 2)
        accepted_sle = sles.get(warehouse=self.accepted_wh)
        rejected_sle = sles.get(warehouse=self.rejected_wh)
        self.assertEqual(accepted_sle.actual_qty, Decimal("7"))
        self.assertEqual(rejected_sle.actual_qty, Decimal("3"))

    def test_submit_with_rejected_qty_no_rejected_warehouse_skips_rejected_sle(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rejected_qty=Decimal("3"),
            uom=self.uom,
            rate=Decimal("100"),
        )
        receipt.submit()
        sles = StockLedgerEntry.objects.filter(voucher_type="Purchase Receipt", voucher_no=str(receipt.pk))
        # Only accepted SLE is created when no rejected warehouse set
        self.assertEqual(sles.count(), 1)
        self.assertEqual(sles[0].actual_qty, Decimal("7"))

    def test_submit_only_on_draft(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        receipt.submit()
        receipt.submit()
        self.assertEqual(receipt.status, "SUBMITTED")

    def test_submitted_stock_visible_in_bin(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("12"),
            uom=self.uom,
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
            accepted_warehouse=self.accepted_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            uom=self.uom,
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
            accepted_warehouse=self.accepted_wh,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            uom=self.uom,
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
            accepted_warehouse=self.accepted_wh,
        )
        receipt.cancel()
        self.assertEqual(receipt.status, "DRAFT")


class PurchaseReceiptStatusTransitionTest(PurchaseReceiptTestBase):
    def test_draft_to_submitted_to_cancelled(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            accepted_warehouse=self.accepted_wh,
        )
        self.assertEqual(receipt.status, "DRAFT")
        receipt.submit()
        self.assertEqual(receipt.status, "SUBMITTED")
        receipt.cancel()
        self.assertEqual(receipt.status, "CANCELLED")

from decimal import Decimal

from django.test import TestCase

from apps.inventory.models import (
    UOM,
    Bin,
    Item,
    ItemGroup,
    StockLedgerEntry,
    StockReconciliation,
    StockReconciliationItem,
    Warehouse,
)
from apps.settings.models import Branch


class ReconciliationTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.warehouse = Warehouse.objects.create(name="Main Store", branch=cls.branch)
        cls.item = Item.objects.create(
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
        )


class StockReconciliationSubmitTest(ReconciliationTestBase):
    def test_submit_adjusts_stock_up(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("5"),
            voucher_type="Opening",
            voucher_no="0",
            rate=Decimal("100"),
        )
        rec = StockReconciliation.objects.create(warehouse=self.warehouse)
        line = StockReconciliationItem.objects.create(
            reconciliation=rec,
            item=self.item,
            qty=Decimal("8"),
        )
        self.assertEqual(line.current_qty, Decimal("5"))

        rec.submit()
        self.assertEqual(rec.status, "SUBMITTED")
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.warehouse)
        self.assertEqual(bin_obj.actual_qty, Decimal("8"))

    def test_submit_adjusts_stock_down(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("10"),
            voucher_type="Opening",
            voucher_no="0",
            rate=Decimal("100"),
        )
        rec = StockReconciliation.objects.create(warehouse=self.warehouse)
        StockReconciliationItem.objects.create(
            reconciliation=rec,
            item=self.item,
            qty=Decimal("3"),
        )
        rec.submit()
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.warehouse)
        self.assertEqual(bin_obj.actual_qty, Decimal("3"))

    def test_submit_no_change_skips_sle(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("5"),
            voucher_type="Opening",
            voucher_no="0",
            rate=Decimal("100"),
        )
        rec = StockReconciliation.objects.create(warehouse=self.warehouse)
        StockReconciliationItem.objects.create(
            reconciliation=rec,
            item=self.item,
            qty=Decimal("5"),
        )
        rec.submit()
        sles = StockLedgerEntry.objects.filter(voucher_type="Stock Reconciliation", voucher_no=str(rec.pk))
        self.assertEqual(sles.count(), 0)

    def test_submit_creates_adjustment_sle(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("5"),
            voucher_type="Opening",
            voucher_no="0",
            rate=Decimal("100"),
        )
        rec = StockReconciliation.objects.create(warehouse=self.warehouse)
        StockReconciliationItem.objects.create(
            reconciliation=rec,
            item=self.item,
            qty=Decimal("10"),
        )
        rec.submit()
        sles = StockLedgerEntry.objects.filter(voucher_type="Stock Reconciliation", voucher_no=str(rec.pk))
        self.assertEqual(sles.count(), 1)
        self.assertEqual(sles[0].actual_qty, Decimal("5"))


class StockReconciliationCancelTest(ReconciliationTestBase):
    def test_cancel_reverses_adjustment(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("5"),
            voucher_type="Opening",
            voucher_no="0",
            rate=Decimal("100"),
        )
        rec = StockReconciliation.objects.create(warehouse=self.warehouse)
        StockReconciliationItem.objects.create(
            reconciliation=rec,
            item=self.item,
            qty=Decimal("10"),
        )
        rec.submit()
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.warehouse)
        self.assertEqual(bin_obj.actual_qty, Decimal("10"))

        rec.cancel()
        self.assertEqual(rec.status, "CANCELLED")
        bin_obj.refresh_from_db()
        self.assertEqual(bin_obj.actual_qty, Decimal("5"))

    def test_cancel_only_on_submitted(self):
        rec = StockReconciliation.objects.create(warehouse=self.warehouse)
        rec.cancel()
        self.assertEqual(rec.status, "DRAFT")


class StockReconciliationOpeningStockTest(ReconciliationTestBase):
    def test_opening_stock_purpose(self):
        rec = StockReconciliation.objects.create(warehouse=self.warehouse, purpose="OPENING_STOCK")
        StockReconciliationItem.objects.create(
            reconciliation=rec,
            item=self.item,
            qty=Decimal("50"),
            valuation_rate=Decimal("100"),
        )
        rec.submit()
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.warehouse)
        self.assertEqual(bin_obj.actual_qty, Decimal("50"))


class StockReconciliationCRUDTest(ReconciliationTestBase):
    def test_create(self):
        rec = StockReconciliation.objects.create(warehouse=self.warehouse)
        self.assertEqual(rec.status, "DRAFT")
        self.assertEqual(rec.purpose, "RECONCILIATION")

    def test_str(self):
        rec = StockReconciliation.objects.create(warehouse=self.warehouse)
        self.assertIn("Stock Reconciliation", str(rec))
        self.assertIn(self.warehouse.name, str(rec))

    def test_default_purpose(self):
        rec = StockReconciliation(warehouse=self.warehouse)
        self.assertEqual(rec.purpose, "RECONCILIATION")

    def test_item_current_qty_auto_filled(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("7"),
            voucher_type="Opening",
            voucher_no="0",
            rate=Decimal("100"),
        )
        rec = StockReconciliation.objects.create(warehouse=self.warehouse)
        line = StockReconciliationItem.objects.create(
            reconciliation=rec,
            item=self.item,
            qty=Decimal("10"),
        )
        self.assertEqual(line.current_qty, Decimal("7"))

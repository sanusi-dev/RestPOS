from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import (
    Bin,
    Item,
    ItemGroup,
    StockEntry,
    StockEntryDetail,
    StockLedgerEntry,
    Warehouse,
)
from apps.settings.models import Branch


class StockEntryTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.wh1 = Warehouse.objects.create(name="Main Store", branch=cls.branch)
        cls.wh2 = Warehouse.objects.create(name="Kitchen Store", branch=cls.branch)
        from apps.inventory.models import UOM

        cls.uom, _ = UOM.objects.get_or_create(name="Nos")
        cls.item = Item.objects.create(
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
        )


class StockEntryDetailValidationTest(StockEntryTestBase):
    def test_receipt_requires_target(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        detail = StockEntryDetail(stock_entry=entry, item=self.item, qty=Decimal("5"), target_warehouse=None)
        with self.assertRaises(ValidationError):
            detail.full_clean()

    def test_receipt_rejects_source(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        detail = StockEntryDetail(
            stock_entry=entry, item=self.item, qty=Decimal("5"), target_warehouse=self.wh1, source_warehouse=self.wh1
        )
        with self.assertRaises(ValidationError):
            detail.full_clean()

    def test_issue_requires_source(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_ISSUE")
        detail = StockEntryDetail(stock_entry=entry, item=self.item, qty=Decimal("5"), source_warehouse=None)
        with self.assertRaises(ValidationError):
            detail.full_clean()

    def test_issue_rejects_target(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_ISSUE")
        detail = StockEntryDetail(
            stock_entry=entry, item=self.item, qty=Decimal("5"), source_warehouse=self.wh1, target_warehouse=self.wh1
        )
        with self.assertRaises(ValidationError):
            detail.full_clean()

    def test_transfer_requires_both(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        detail = StockEntryDetail(
            stock_entry=entry, item=self.item, qty=Decimal("5"), source_warehouse=None, target_warehouse=None
        )
        with self.assertRaises(ValidationError):
            detail.full_clean()

    def test_transfer_with_both_ok(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        detail = StockEntryDetail(
            stock_entry=entry, item=self.item, qty=Decimal("5"), source_warehouse=self.wh1, target_warehouse=self.wh2
        )
        detail.full_clean()

    def test_default_status_draft(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        self.assertEqual(entry.status, "DRAFT")


class StockEntrySubmitTest(StockEntryTestBase):
    def test_material_receipt_submit(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        StockEntryDetail.objects.create(
            stock_entry=entry,
            item=self.item,
            target_warehouse=self.wh1,
            qty=Decimal("10"),
            basic_rate=Decimal("100"),
        )
        entry.submit()
        self.assertEqual(entry.status, "SUBMITTED")
        sles = StockLedgerEntry.objects.filter(voucher_type="Stock Entry", voucher_no=str(entry.pk))
        self.assertEqual(sles.count(), 1)
        self.assertEqual(sles[0].actual_qty, Decimal("10"))
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.wh1)
        self.assertEqual(bin_obj.actual_qty, Decimal("10"))

    def test_material_receipt_updates_last_purchase_rate(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        StockEntryDetail.objects.create(
            stock_entry=entry,
            item=self.item,
            target_warehouse=self.wh1,
            qty=Decimal("10"),
            basic_rate=Decimal("350"),
        )
        entry.submit()
        self.item.refresh_from_db()
        self.assertEqual(self.item.last_purchase_rate, Decimal("350"))

    def test_material_issue_submit(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.wh1,
            actual_qty=Decimal("10"),
            voucher_type="Opening",
            voucher_no="0",
            rate=Decimal("100"),
        )
        entry = StockEntry.objects.create(purpose="MATERIAL_ISSUE")
        StockEntryDetail.objects.create(
            stock_entry=entry,
            item=self.item,
            source_warehouse=self.wh1,
            qty=Decimal("4"),
        )
        entry.submit()
        self.assertEqual(entry.status, "SUBMITTED")
        sles = StockLedgerEntry.objects.filter(voucher_type="Stock Entry", voucher_no=str(entry.pk))
        self.assertEqual(sles.count(), 1)
        self.assertEqual(sles[0].actual_qty, Decimal("-4"))
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.wh1)
        self.assertEqual(bin_obj.actual_qty, Decimal("6"))

    def test_material_transfer_submit_creates_two_sles(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.wh1,
            actual_qty=Decimal("10"),
            voucher_type="Opening",
            voucher_no="0",
            rate=Decimal("100"),
        )
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        StockEntryDetail.objects.create(
            stock_entry=entry,
            item=self.item,
            source_warehouse=self.wh1,
            target_warehouse=self.wh2,
            qty=Decimal("5"),
        )
        entry.submit()
        self.assertEqual(entry.status, "SUBMITTED")
        sles = StockLedgerEntry.objects.filter(voucher_type="Stock Entry", voucher_no=str(entry.pk))
        self.assertEqual(sles.count(), 2)
        actual_qtys = sorted(sles.values_list("actual_qty", flat=True))
        self.assertEqual(actual_qtys, [Decimal("-5"), Decimal("5")])
        bin1 = Bin.objects.get(item=self.item, warehouse=self.wh1)
        bin2 = Bin.objects.get(item=self.item, warehouse=self.wh2)
        self.assertEqual(bin1.actual_qty, Decimal("5"))
        self.assertEqual(bin2.actual_qty, Decimal("5"))


class StockEntryCancelTest(StockEntryTestBase):
    def test_cancel_reverses_receipt(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        StockEntryDetail.objects.create(
            stock_entry=entry,
            item=self.item,
            target_warehouse=self.wh1,
            qty=Decimal("10"),
            basic_rate=Decimal("100"),
        )
        entry.submit()
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.wh1)
        self.assertEqual(bin_obj.actual_qty, Decimal("10"))

        entry.cancel()
        self.assertEqual(entry.status, "CANCELLED")
        bin_obj.refresh_from_db()
        self.assertEqual(bin_obj.actual_qty, Decimal("0"))

    def test_cancel_reverses_transfer(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.wh1,
            actual_qty=Decimal("10"),
            voucher_type="Opening",
            voucher_no="0",
            rate=Decimal("100"),
        )
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        StockEntryDetail.objects.create(
            stock_entry=entry,
            item=self.item,
            source_warehouse=self.wh1,
            target_warehouse=self.wh2,
            qty=Decimal("5"),
        )
        entry.submit()
        entry.cancel()
        self.assertEqual(entry.status, "CANCELLED")
        bin1 = Bin.objects.get(item=self.item, warehouse=self.wh1)
        bin2 = Bin.objects.get(item=self.item, warehouse=self.wh2)
        self.assertEqual(bin1.actual_qty, Decimal("10"))
        self.assertEqual(bin2.actual_qty, Decimal("0"))

    def test_cancel_only_on_submitted(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        entry.cancel()
        self.assertEqual(entry.status, "DRAFT")

    def test_submit_only_on_draft(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        entry.submit()
        entry.submit()
        self.assertEqual(entry.status, "SUBMITTED")


class StockEntryCRUDTest(StockEntryTestBase):
    def test_create(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        self.assertEqual(entry.purpose, "MATERIAL_RECEIPT")
        self.assertEqual(entry.status, "DRAFT")

    def test_str(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        self.assertIn("MATERIAL_RECEIPT", str(entry))

    def test_create_detail(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        detail = StockEntryDetail.objects.create(
            stock_entry=entry, item=self.item, target_warehouse=self.wh1, qty=Decimal("5")
        )
        self.assertIn(detail, entry.items.all())
        self.assertIn("x5", str(detail))

import json
from decimal import Decimal

from django.test import TestCase

from apps.inventory.models import (
    UOM,
    Bin,
    Item,
    ItemGroup,
    StockLedgerEntry,
    Warehouse,
)


class StockLedgerEntryTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.warehouse = Warehouse.objects.create(name="Main Store")
        cls.item = Item.objects.create(
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
        )


class CreateEntryTest(StockLedgerEntryTestBase):
    def test_receipt_creates_sle(self):
        sle = StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("10"),
            voucher_type="Stock Entry",
            voucher_no="SE1",
            rate=Decimal("100"),
        )
        self.assertEqual(sle.actual_qty, Decimal("10"))
        self.assertEqual(sle.qty_after_transaction, Decimal("10"))
        self.assertEqual(sle.incoming_rate, Decimal("100"))

    def test_receipt_updates_bin(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("10"),
            voucher_type="Stock Entry",
            voucher_no="SE1",
            rate=Decimal("100"),
        )
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.warehouse)
        self.assertEqual(bin_obj.actual_qty, Decimal("10"))

    def test_issue_creates_negative_sle(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("10"),
            voucher_type="Stock Entry",
            voucher_no="SE1",
            rate=Decimal("100"),
        )
        sle = StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("-4"),
            voucher_type="Stock Entry",
            voucher_no="SE2",
        )
        self.assertEqual(sle.actual_qty, Decimal("-4"))
        self.assertEqual(sle.qty_after_transaction, Decimal("6"))

    def test_issue_updates_bin(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("10"),
            voucher_type="Stock Entry",
            voucher_no="SE1",
            rate=Decimal("100"),
        )
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("-4"),
            voucher_type="Stock Entry",
            voucher_no="SE2",
        )
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.warehouse)
        self.assertEqual(bin_obj.actual_qty, Decimal("6"))


class RunningBalanceTest(StockLedgerEntryTestBase):
    def test_qty_after_transaction_running_balance(self):
        sle1 = StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("10"),
            voucher_type="T",
            voucher_no="1",
            rate=Decimal("100"),
        )
        sle2 = StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("5"),
            voucher_type="T",
            voucher_no="2",
            rate=Decimal("120"),
        )
        sle3 = StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("-3"),
            voucher_type="T",
            voucher_no="3",
        )
        self.assertEqual(sle1.qty_after_transaction, Decimal("10"))
        self.assertEqual(sle2.qty_after_transaction, Decimal("15"))
        self.assertEqual(sle3.qty_after_transaction, Decimal("12"))


class FIFOQueueTest(StockLedgerEntryTestBase):
    def test_fifo_queue_appends_on_receipt(self):
        sle = StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("10"),
            voucher_type="T",
            voucher_no="1",
            rate=Decimal("100"),
        )
        queue = json.loads(sle.stock_queue)
        self.assertEqual(len(queue), 1)
        self.assertEqual(Decimal(queue[0][0]), Decimal("10"))
        self.assertEqual(Decimal(queue[0][1]), Decimal("100"))

    def test_fifo_queue_pops_on_issue(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("10"),
            voucher_type="T",
            voucher_no="1",
            rate=Decimal("100"),
        )
        sle2 = StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("-4"),
            voucher_type="T",
            voucher_no="2",
        )
        queue = json.loads(sle2.stock_queue)
        self.assertEqual(len(queue), 1)
        self.assertEqual(Decimal(queue[0][0]), Decimal("6"))

    def test_fifo_outgoing_rate_from_first_layer(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("10"),
            voucher_type="T",
            voucher_no="1",
            rate=Decimal("100"),
        )
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("10"),
            voucher_type="T",
            voucher_no="2",
            rate=Decimal("200"),
        )
        sle_out = StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("-5"),
            voucher_type="T",
            voucher_no="3",
        )
        self.assertEqual(sle_out.outgoing_rate, Decimal("100"))

    def test_fifo_outgoing_rate_consumes_first_layer_then_second(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("5"),
            voucher_type="T",
            voucher_no="1",
            rate=Decimal("100"),
        )
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("5"),
            voucher_type="T",
            voucher_no="2",
            rate=Decimal("200"),
        )
        sle_out = StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("-7"),
            voucher_type="T",
            voucher_no="3",
        )
        expected = (Decimal("5") * Decimal("100") + Decimal("2") * Decimal("200")) / Decimal("7")
        self.assertEqual(sle_out.outgoing_rate, expected)

    def test_fifo_valuation_rate_after_full_issue(self):
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("10"),
            voucher_type="T",
            voucher_no="1",
            rate=Decimal("100"),
        )
        sle_out = StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            actual_qty=Decimal("-10"),
            voucher_type="T",
            voucher_no="2",
        )
        self.assertEqual(sle_out.valuation_rate, Decimal("0"))
        bin_obj = Bin.objects.get(item=self.item, warehouse=self.warehouse)
        self.assertEqual(bin_obj.actual_qty, Decimal("0"))


class SLEFieldsNotEditable(StockLedgerEntryTestBase):
    def test_actual_qty_not_editable(self):
        field = StockLedgerEntry._meta.get_field("actual_qty")
        self.assertFalse(field.editable)

    def test_qty_after_transaction_not_editable(self):
        field = StockLedgerEntry._meta.get_field("qty_after_transaction")
        self.assertFalse(field.editable)

    def test_valuation_rate_not_editable(self):
        field = StockLedgerEntry._meta.get_field("valuation_rate")
        self.assertFalse(field.editable)

    def test_is_cancelled_not_editable(self):
        field = StockLedgerEntry._meta.get_field("is_cancelled")
        self.assertFalse(field.editable)

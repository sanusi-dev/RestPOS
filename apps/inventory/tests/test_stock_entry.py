from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import (
    UOM,
    Bin,
    Item,
    ItemGroup,
    StockEntry,
    StockEntryDetail,
    StockLedgerEntry,
    Warehouse,
)
from apps.inventory.services import cancel_stock_entry, submit_stock_entry
from apps.settings.models import ProductionUnit, Restaurant


class StockEntryTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Stock")
        cls.store = Warehouse.objects.create(name="Store")
        cls.kitchen = Warehouse.objects.create(name="Kitchen")
        cls.bar = Warehouse.objects.create(name="Bar")
        cls.restaurant = Restaurant.objects.create(
            company="Test Restaurant", store_warehouse=cls.store, default_warehouse=cls.bar
        )
        ProductionUnit.objects.create(name="Kitchen", department="FOOD", warehouse=cls.kitchen)
        ProductionUnit.objects.create(name="Bar", department="DRINKS", warehouse=cls.bar)
        cls.food = Item.objects.create(
            item_name="Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_stock_item=True,
            is_purchase_item=True,
        )
        cls.drink = Item.objects.create(
            item_name="Cola",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="DRINKS",
            is_stock_item=True,
            is_purchase_item=True,
        )

    def test_choices_exclude_material_issue(self):
        values = {value for value, _label in StockEntry._meta.get_field("purpose").choices}
        self.assertEqual(values, {"MATERIAL_RECEIPT", "MATERIAL_TRANSFER"})

    def test_receipt_forces_store_and_requires_purchasable_stock_item(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        line = StockEntryDetail.objects.create(
            stock_entry=entry, item=self.food, target_warehouse=self.bar, qty=Decimal("4"), basic_rate=Decimal("50")
        )
        with self.assertRaisesMessage(ValidationError, "central Store"):
            submit_stock_entry(entry)
        line.target_warehouse = None
        line.save()
        submit_stock_entry(entry)
        line.refresh_from_db()
        self.assertEqual(line.target_warehouse, self.store)
        self.assertEqual(Bin.objects.get(item=self.food, warehouse=self.store).actual_qty, Decimal("4"))

    def test_receipt_rejects_non_purchase_item(self):
        self.food.is_purchase_item = False
        self.food.save()
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        StockEntryDetail.objects.create(stock_entry=entry, item=self.food, qty=1)
        with self.assertRaisesMessage(ValidationError, "not purchasable"):
            submit_stock_entry(entry)

    def test_transfer_derives_department_targets_and_preserves_fifo_rate(self):
        # Two FIFO layers make the three-unit transfer rate 133.33 (2 at 100,
        # then 1 at 200), proving transfer-in inherits source cost.
        StockLedgerEntry.create_entry(self.food, self.store, Decimal("2"), "Opening", "1", rate=Decimal("100"))
        StockLedgerEntry.create_entry(self.food, self.store, Decimal("3"), "Opening", "2", rate=Decimal("200"))
        StockLedgerEntry.create_entry(self.drink, self.store, Decimal("2"), "Opening", "3", rate=Decimal("75"))
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        food_line = StockEntryDetail.objects.create(stock_entry=entry, item=self.food, qty=Decimal("3"))
        drink_line = StockEntryDetail.objects.create(stock_entry=entry, item=self.drink, qty=Decimal("2"))

        submit_stock_entry(entry)

        food_line.refresh_from_db()
        drink_line.refresh_from_db()
        self.assertEqual((food_line.source_warehouse, food_line.target_warehouse), (self.store, self.kitchen))
        self.assertEqual((drink_line.source_warehouse, drink_line.target_warehouse), (self.store, self.bar))
        food_in = StockLedgerEntry.objects.get(
            voucher_type="Stock Entry", voucher_no=str(entry.pk), voucher_detail_no=str(food_line.pk), actual_qty__gt=0
        )
        self.assertEqual(food_in.incoming_rate, Decimal("133.33"))

    def test_transfer_rejects_override_and_negative_store(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        line = StockEntryDetail.objects.create(
            stock_entry=entry, item=self.food, source_warehouse=self.bar, target_warehouse=self.store, qty=1
        )
        with self.assertRaises(ValidationError):
            submit_stock_entry(entry)
        line.source_warehouse = None
        line.target_warehouse = None
        line.save()
        with self.assertRaisesMessage(ValidationError, "Insufficient stock"):
            submit_stock_entry(entry)
        self.assertEqual(
            StockLedgerEntry.objects.filter(voucher_type="Stock Entry", voucher_no=str(entry.pk)).count(), 0
        )

    def test_transfer_submit_and_cancel_are_idempotent(self):
        StockLedgerEntry.create_entry(self.food, self.store, Decimal("5"), "Opening", "1", rate=Decimal("100"))
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        StockEntryDetail.objects.create(stock_entry=entry, item=self.food, qty=Decimal("2"))
        submit_stock_entry(entry)
        submit_stock_entry(entry)
        self.assertEqual(
            StockLedgerEntry.objects.filter(voucher_type="Stock Entry", voucher_no=str(entry.pk)).count(), 2
        )
        cancel_stock_entry(entry)
        cancel_stock_entry(entry)
        self.assertEqual(Bin.objects.get(item=self.food, warehouse=self.store).actual_qty, Decimal("5"))
        self.assertEqual(Bin.objects.get(item=self.food, warehouse=self.kitchen).actual_qty, Decimal("0"))

    def test_cancel_transfer_rejects_consumed_target_atomically(self):
        StockLedgerEntry.create_entry(self.food, self.store, Decimal("5"), "Opening", "1", rate=Decimal("100"))
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        StockEntryDetail.objects.create(stock_entry=entry, item=self.food, qty=Decimal("2"))
        submit_stock_entry(entry)
        StockLedgerEntry.create_entry(self.food, self.kitchen, Decimal("-2"), "Consumption", "1")
        with self.assertRaises(ValidationError):
            cancel_stock_entry(entry)
        entry.refresh_from_db()
        self.assertEqual(entry.status, "SUBMITTED")
        self.assertFalse(StockLedgerEntry.objects.filter(voucher_type="Stock Entry Cancellation").exists())

    def test_cancel_transfer_uses_current_target_fifo_and_original_source_rate(self):
        # The target already has a newer 300-rate layer; cancellation must use
        # that current target cost while restoring the source at its original rate.
        StockLedgerEntry.create_entry(self.food, self.store, Decimal("2"), "Opening", "1", rate=Decimal("100"))
        StockLedgerEntry.create_entry(self.food, self.kitchen, Decimal("1"), "Opening", "2", rate=Decimal("300"))
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        StockEntryDetail.objects.create(stock_entry=entry, item=self.food, qty=Decimal("1"))
        submit_stock_entry(entry)

        cancel_stock_entry(entry)

        reversals = StockLedgerEntry.objects.filter(voucher_type="Stock Entry Cancellation", voucher_no=str(entry.pk))
        target_reversal = reversals.get(warehouse=self.kitchen)
        source_reversal = reversals.get(warehouse=self.store)
        self.assertEqual(target_reversal.outgoing_rate, Decimal("300"))
        self.assertEqual(source_reversal.incoming_rate, Decimal("100"))
        kitchen_bin = Bin.objects.get(item=self.food, warehouse=self.kitchen)
        self.assertEqual(kitchen_bin.actual_qty, Decimal("1"))
        self.assertEqual(kitchen_bin.valuation_rate, Decimal("100"))

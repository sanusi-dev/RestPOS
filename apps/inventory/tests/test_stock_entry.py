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
        from apps.accounting.tests.helpers import setup_chart_of_accounts

        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Stock")
        cls.store = Warehouse.objects.create(name="Store")
        cls.kitchen = Warehouse.objects.create(name="Kitchen")
        cls.bar = Warehouse.objects.create(name="Bar")
        cls.restaurant = Restaurant.objects.create(
            company="Test Restaurant", store_warehouse=cls.store, default_warehouse=cls.bar
        )
        cls.accounts = setup_chart_of_accounts(cls.restaurant)
        for wh in [cls.store, cls.kitchen, cls.bar]:
            wh.account = cls.accounts["stock_in_hand"]
            wh.save(update_fields=["account", "updated_at"])
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

    def test_transfer_derives_department_targets_and_preserves_wac_rate(self):
        # WAC: store 2@100 + 3@200 => WAC 160. Transfer 3 at source WAC 160.
        StockLedgerEntry.create_entry(
            item=self.food,
            warehouse=self.store,
            quantity=Decimal("2"),
            voucher_type="Opening",
            voucher_no="1",
            unit_rate=Decimal("100"),
        )
        StockLedgerEntry.create_entry(
            item=self.food,
            warehouse=self.store,
            quantity=Decimal("3"),
            voucher_type="Opening",
            voucher_no="2",
            unit_rate=Decimal("200"),
        )
        StockLedgerEntry.create_entry(
            item=self.drink,
            warehouse=self.store,
            quantity=Decimal("2"),
            voucher_type="Opening",
            voucher_no="3",
            unit_rate=Decimal("75"),
        )
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        food_line = StockEntryDetail.objects.create(stock_entry=entry, item=self.food, qty=Decimal("3"))
        drink_line = StockEntryDetail.objects.create(stock_entry=entry, item=self.drink, qty=Decimal("2"))

        submit_stock_entry(entry)

        food_line.refresh_from_db()
        drink_line.refresh_from_db()
        self.assertEqual((food_line.source_warehouse, food_line.target_warehouse), (self.store, self.kitchen))
        self.assertEqual((drink_line.source_warehouse, drink_line.target_warehouse), (self.store, self.bar))
        food_in = StockLedgerEntry.objects.get(
            voucher_type="Stock Entry", voucher_no=str(entry.pk), voucher_detail_no=str(food_line.pk), quantity__gt=0
        )
        self.assertEqual(food_in.unit_rate, Decimal("160"))

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
        StockLedgerEntry.create_entry(
            item=self.food,
            warehouse=self.store,
            quantity=Decimal("5"),
            voucher_type="Opening",
            voucher_no="1",
            unit_rate=Decimal("100"),
        )
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
        StockLedgerEntry.create_entry(
            item=self.food,
            warehouse=self.store,
            quantity=Decimal("5"),
            voucher_type="Opening",
            voucher_no="1",
            unit_rate=Decimal("100"),
        )
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        StockEntryDetail.objects.create(stock_entry=entry, item=self.food, qty=Decimal("2"))
        submit_stock_entry(entry)
        StockLedgerEntry.create_entry(
            item=self.food, warehouse=self.kitchen, quantity=Decimal("-2"), voucher_type="Consumption", voucher_no="1"
        )
        with self.assertRaises(ValidationError):
            cancel_stock_entry(entry)
        entry.refresh_from_db()
        self.assertEqual(entry.status, "SUBMITTED")
        self.assertFalse(StockLedgerEntry.objects.filter(voucher_type="Stock Entry Cancellation").exists())

    def test_cancel_transfer_uses_current_target_wac(self):
        # Store 2@100, kitchen 1@300. Transfer 1 at store WAC 100.
        # After transfer: kitchen WAC (1*300+1*100)/2=200. Cancel uses dest current WAC 200.
        StockLedgerEntry.create_entry(
            item=self.food,
            warehouse=self.store,
            quantity=Decimal("2"),
            voucher_type="Opening",
            voucher_no="1",
            unit_rate=Decimal("100"),
        )
        StockLedgerEntry.create_entry(
            item=self.food,
            warehouse=self.kitchen,
            quantity=Decimal("1"),
            voucher_type="Opening",
            voucher_no="2",
            unit_rate=Decimal("300"),
        )
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        StockEntryDetail.objects.create(stock_entry=entry, item=self.food, qty=Decimal("1"))
        submit_stock_entry(entry)

        cancel_stock_entry(entry)

        reversals = StockLedgerEntry.objects.filter(voucher_type="Stock Entry Cancellation", voucher_no=str(entry.pk))
        target_reversal = reversals.get(warehouse=self.kitchen)
        source_reversal = reversals.get(warehouse=self.store)
        self.assertEqual(target_reversal.unit_rate, Decimal("200"))
        self.assertEqual(target_reversal.quantity, Decimal("-1"))
        # Source reversal inbound at dest WAC 200
        self.assertEqual(source_reversal.unit_rate, Decimal("200"))
        self.assertEqual(source_reversal.quantity, Decimal("1"))
        kitchen_bin = Bin.objects.get(item=self.food, warehouse=self.kitchen)
        self.assertEqual(kitchen_bin.actual_qty, Decimal("1"))
        self.assertEqual(kitchen_bin.valuation_rate, Decimal("200"))
        # Store after cancel: 1*100 +1*200 blended => 150
        store_bin = Bin.objects.get(item=self.food, warehouse=self.store)
        self.assertEqual(store_bin.actual_qty, Decimal("2"))
        self.assertEqual(store_bin.valuation_rate, Decimal("150"))

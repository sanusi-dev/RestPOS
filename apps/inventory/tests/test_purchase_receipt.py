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
from apps.settings.models import Restaurant


class PurchaseReceiptTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Stock")
        cls.store = Warehouse.objects.create(name="Store")
        cls.other = Warehouse.objects.create(name="Other")
        Restaurant.objects.create(company="Test", store_warehouse=cls.store)
        cls.item = Item.objects.create(
            item_name="Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_stock_item=True,
            is_purchase_item=True,
        )

    def test_submit_forces_configured_store(self):
        receipt = PurchaseReceipt.objects.create(supplier_name="Supplier", warehouse=self.store)
        PurchaseReceiptItem.objects.create(purchase_receipt=receipt, item=self.item, received_qty=10, rate=100)
        receipt.submit()
        receipt.refresh_from_db()
        self.assertEqual(receipt.warehouse, self.store)
        self.assertEqual(receipt.total, Decimal("1000"))
        self.assertEqual(Bin.objects.get(item=self.item, warehouse=self.store).actual_qty, Decimal("10"))

    def test_submit_rejects_overridden_warehouse(self):
        receipt = PurchaseReceipt.objects.create(supplier_name="Supplier", warehouse=self.other)
        PurchaseReceiptItem.objects.create(purchase_receipt=receipt, item=self.item, received_qty=1, rate=10)
        with self.assertRaisesMessage(ValidationError, "central Store"):
            receipt.submit()

    def test_submit_rejects_non_stock_non_purchase_disabled_and_template_items(self):
        for changes in (
            {"is_stock_item": False},
            {"is_purchase_item": False},
            {"disabled": True},
            {"has_variants": True},
        ):
            values = {"is_stock_item": True, "is_purchase_item": True, "disabled": False, "has_variants": False}
            values.update(changes)
            Item.objects.filter(pk=self.item.pk).update(**values)
            self.item.refresh_from_db()
            receipt = PurchaseReceipt.objects.create(supplier_name="Supplier", warehouse=self.store)
            PurchaseReceiptItem.objects.create(purchase_receipt=receipt, item=self.item, received_qty=1, rate=10)
            with self.assertRaisesMessage(ValidationError, "enabled stock and purchase item"):
                receipt.submit()

    def test_cancel_is_idempotent(self):
        receipt = PurchaseReceipt.objects.create(supplier_name="Supplier", warehouse=self.store)
        PurchaseReceiptItem.objects.create(purchase_receipt=receipt, item=self.item, received_qty=2, rate=10)
        receipt.submit()
        receipt.cancel()
        receipt.cancel()
        self.assertEqual(Bin.objects.get(item=self.item, warehouse=self.store).actual_qty, Decimal("0"))

    def test_cancel_rejects_consumed_stock_and_rolls_back_all_reversals(self):
        second_item = Item.objects.create(
            item_name="Beans",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            is_stock_item=True,
            is_purchase_item=True,
        )
        receipt = PurchaseReceipt.objects.create(supplier_name="Supplier", warehouse=self.store)
        PurchaseReceiptItem.objects.create(purchase_receipt=receipt, item=self.item, received_qty=2, rate=10)
        PurchaseReceiptItem.objects.create(purchase_receipt=receipt, item=second_item, received_qty=2, rate=20)
        receipt.submit()
        StockLedgerEntry.create_entry(second_item, self.store, -2, "Consumption", "1")

        with self.assertRaisesMessage(ValidationError, "Insufficient stock"):
            receipt.cancel()

        receipt.refresh_from_db()
        self.assertEqual(receipt.status, "SUBMITTED")
        self.assertEqual(Bin.objects.get(item=self.item, warehouse=self.store).actual_qty, Decimal("2"))
        self.assertFalse(StockLedgerEntry.objects.filter(voucher_type="Purchase Receipt Cancellation").exists())
        self.assertFalse(
            StockLedgerEntry.objects.filter(
                voucher_type="Purchase Receipt", voucher_no=str(receipt.pk), is_cancelled=True
            ).exists()
        )

    def test_cancel_consumes_current_fifo_and_preserves_remaining_valuation(self):
        receipt = PurchaseReceipt.objects.create(supplier_name="Supplier", warehouse=self.store)
        PurchaseReceiptItem.objects.create(purchase_receipt=receipt, item=self.item, received_qty=2, rate=100)
        receipt.submit()
        StockLedgerEntry.create_entry(self.item, self.store, 2, "Later Receipt", "1", rate=Decimal("200"))

        receipt.cancel()

        stock_bin = Bin.objects.get(item=self.item, warehouse=self.store)
        reversal = StockLedgerEntry.objects.get(
            voucher_type="Purchase Receipt Cancellation", voucher_no=str(receipt.pk)
        )
        self.assertEqual(reversal.outgoing_rate, Decimal("100"))
        self.assertEqual(stock_bin.actual_qty, Decimal("2"))
        self.assertEqual(stock_bin.valuation_rate, Decimal("200"))
        self.assertEqual(stock_bin.stock_value, Decimal("400"))

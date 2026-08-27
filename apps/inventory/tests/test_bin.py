from decimal import Decimal

from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup, Warehouse


class BinModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.item = Item.objects.create(
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
        )
        cls.warehouse = Warehouse.objects.create(name="Main Store")

    def test_get_or_create_creates_bin(self):
        bin_obj = Warehouse  # placeholder to avoid linter
        from apps.inventory.models import Bin

        bin_obj = Bin.get_or_create_bin(self.item, self.warehouse)
        self.assertIsNotNone(bin_obj)
        self.assertEqual(bin_obj.actual_qty, Decimal("0"))
        self.assertEqual(bin_obj.valuation_rate, Decimal("0"))

    def test_get_or_create_returns_existing(self):
        from apps.inventory.models import Bin

        bin1 = Bin.get_or_create_bin(self.item, self.warehouse)
        bin2 = Bin.get_or_create_bin(self.item, self.warehouse)
        self.assertEqual(bin1.pk, bin2.pk)

    def test_bin_defaults(self):
        from apps.inventory.models import Bin

        bin_obj = Bin.objects.create(item=self.item, warehouse=self.warehouse)
        self.assertEqual(bin_obj.actual_qty, Decimal("0"))
        self.assertEqual(bin_obj.reserved_qty, Decimal("0"))
        self.assertEqual(bin_obj.valuation_rate, Decimal("0"))
        self.assertEqual(bin_obj.stock_value, Decimal("0"))

    def test_bin_unique_together(self):
        from django.db.utils import IntegrityError

        from apps.inventory.models import Bin

        Bin.objects.create(item=self.item, warehouse=self.warehouse)
        with self.assertRaises(IntegrityError):
            Bin.objects.create(item=self.item, warehouse=self.warehouse)

    def test_bin_str(self):
        from apps.inventory.models import Bin

        bin_obj = Bin.get_or_create_bin(self.item, self.warehouse)
        expected = f"{self.item.item_code} @ {self.warehouse.name}: 0"
        self.assertEqual(str(bin_obj), expected)

    def test_actual_qty_updates_after_sle(self):
        from apps.inventory.models import Bin, StockLedgerEntry

        bin_obj = Bin.get_or_create_bin(self.item, self.warehouse)
        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            quantity=Decimal("10"),
            voucher_type="Stock Entry",
            voucher_no="SE1",
            unit_rate=Decimal("100"),
        )
        bin_obj.refresh_from_db()
        self.assertEqual(bin_obj.actual_qty, Decimal("10"))

        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=self.warehouse,
            quantity=Decimal("-3"),
            voucher_type="Stock Entry",
            voucher_no="SE2",
        )
        bin_obj.refresh_from_db()
        self.assertEqual(bin_obj.actual_qty, Decimal("7"))

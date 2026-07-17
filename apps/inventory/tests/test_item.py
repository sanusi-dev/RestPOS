from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import (
    UOM,
    Item,
    ItemBarcode,
    ItemGroup,
    ItemUOMConversion,
    ReorderLevel,
    Warehouse,
)
from apps.settings.models import Branch


class ItemTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.warehouse = Warehouse.objects.create(name="Main Store", branch=cls.branch)
        cls.item = Item.objects.create(
            item_code="RICE001",
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
        )


class ItemModelTest(ItemTestBase):
    def test_str_returns_item_name(self):
        self.assertEqual(str(self.item), "Jollof Rice")

    def test_str_falls_back_to_item_code(self):
        item = Item.objects.create(
            item_code="BEV001",
            item_name="",
            item_group=self.group,
            stock_uom=self.uom,
            department="DRINKS",
        )
        self.assertEqual(str(item), "BEV001")

    def test_defaults(self):
        self.assertTrue(self.item.is_stock_item)
        self.assertFalse(self.item.disabled)
        self.assertFalse(self.item.has_batch_no)
        self.assertFalse(self.item.has_variants)
        self.assertEqual(self.item.valuation_method, "FIFO")
        self.assertEqual(self.item.safety_stock, Decimal("0"))

    def test_item_code_unique(self):
        from django.db.utils import IntegrityError

        with self.assertRaises(IntegrityError):
            Item.objects.create(
                item_code="RICE001",
                item_name="Duplicate",
                item_group=self.group,
                stock_uom=self.uom,
                department="FOOD",
            )

    def test_department_choices(self):
        self.assertEqual(self.item.get_department_display(), "Food")
        item = Item.objects.create(
            item_code="BEER001",
            item_name="Beer",
            item_group=self.group,
            stock_uom=self.uom,
            department="DRINKS",
        )
        self.assertEqual(item.get_department_display(), "Drinks")

    def test_update(self):
        self.item.item_name = "Special Jollof"
        self.item.save()
        self.item.refresh_from_db()
        self.assertEqual(self.item.item_name, "Special Jollof")

    def test_delete(self):
        pk = self.item.pk
        self.item.delete()
        self.assertFalse(Item.objects.filter(pk=pk).exists())

    def test_ordering(self):
        Item.objects.create(
            item_code="BEV001",
            item_name="Apple Juice",
            item_group=self.group,
            stock_uom=self.uom,
            department="DRINKS",
        )
        names = list(Item.objects.values_list("item_name", flat=True))
        self.assertEqual(names, sorted(names))


class ItemValidationTest(ItemTestBase):
    def test_has_variants_and_is_stock_item_raises(self):
        self.item.has_variants = True
        self.item.is_stock_item = True
        with self.assertRaises(ValidationError):
            self.item.full_clean()

    def test_has_variants_without_stock_ok(self):
        self.item.has_variants = True
        self.item.is_stock_item = False
        self.item.full_clean()

    def test_variant_of_without_parent_has_variants_raises(self):
        parent = Item.objects.create(
            item_code="TMPL001",
            item_name="Template",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            has_variants=False,
            is_stock_item=False,
        )
        variant = Item(
            item_code="VAR001",
            item_name="Variant",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            variant_of=parent,
        )
        with self.assertRaises(ValidationError):
            variant.full_clean()

    def test_variant_of_with_parent_has_variants_ok(self):
        parent = Item.objects.create(
            item_code="TMPL001",
            item_name="Template",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            has_variants=True,
            is_stock_item=False,
        )
        variant = Item(
            item_code="VAR001",
            item_name="Variant",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            variant_of=parent,
        )
        variant.full_clean()

    def test_expiry_without_batch_raises(self):
        self.item.has_expiry_date = True
        self.item.has_batch_no = False
        self.item.shelf_life_in_days = 30
        with self.assertRaises(ValidationError):
            self.item.full_clean()

    def test_expiry_without_shelf_life_raises(self):
        self.item.has_expiry_date = True
        self.item.has_batch_no = True
        self.item.shelf_life_in_days = None
        with self.assertRaises(ValidationError):
            self.item.full_clean()

    def test_expiry_with_batch_and_shelf_life_ok(self):
        self.item.has_expiry_date = True
        self.item.has_batch_no = True
        self.item.shelf_life_in_days = 30
        self.item.full_clean()


class ItemChildTableTest(ItemTestBase):
    def test_create_barcode(self):
        bc = ItemBarcode.objects.create(item=self.item, barcode="1234567890")
        self.assertEqual(str(bc), "1234567890")
        self.assertIn(bc, self.item.barcodes.all())

    def test_barcode_unique(self):
        from django.db.utils import IntegrityError

        ItemBarcode.objects.create(item=self.item, barcode="1234567890")
        with self.assertRaises(IntegrityError):
            ItemBarcode.objects.create(item=self.item, barcode="1234567890")

    def test_create_uom_conversion(self):
        box = UOM.objects.create(name="Box")
        conv = ItemUOMConversion.objects.create(item=self.item, uom=box, conversion_factor=Decimal("12"))
        self.assertEqual(str(conv), "Box (x12)")
        self.assertIn(conv, self.item.uom_conversions.all())

    def test_uom_conversion_unique(self):
        from django.db.utils import IntegrityError

        box = UOM.objects.create(name="Box")
        ItemUOMConversion.objects.create(item=self.item, uom=box, conversion_factor=Decimal("12"))
        with self.assertRaises(IntegrityError):
            ItemUOMConversion.objects.create(item=self.item, uom=box, conversion_factor=Decimal("6"))

    def test_create_reorder_level(self):
        rl = ReorderLevel.objects.create(
            item=self.item, warehouse=self.warehouse, reorder_level=Decimal("10"), reorder_qty=Decimal("20")
        )
        self.assertIn(rl, self.item.reorder_levels.all())
        self.assertEqual(rl.reorder_level, Decimal("10"))

    def test_reorder_level_unique(self):
        from django.db.utils import IntegrityError

        ReorderLevel.objects.create(item=self.item, warehouse=self.warehouse)
        with self.assertRaises(IntegrityError):
            ReorderLevel.objects.create(item=self.item, warehouse=self.warehouse)

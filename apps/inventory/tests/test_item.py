from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import (
    UOM,
    Item,
    ItemGroup,
    Warehouse,
)


class ItemTestBase(TestCase):
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


class ItemModelTest(ItemTestBase):
    def test_str_returns_item_name(self):
        self.assertEqual(str(self.item), "Jollof Rice")

    def test_str_falls_back_to_item_code(self):
        item = Item.objects.create(
            item_name="",
            item_group=self.group,
            stock_uom=self.uom,
            department="DRINKS",
        )
        self.assertTrue(item.item_code.startswith("ITEM-"))
        self.assertEqual(str(item), item.item_code)

    def test_defaults(self):
        self.assertTrue(self.item.is_stock_item)
        self.assertFalse(self.item.is_sales_item)
        self.assertFalse(self.item.is_purchase_item)
        self.assertFalse(self.item.disabled)
        self.assertFalse(self.item.has_variants)
        self.assertEqual(self.item.safety_stock, Decimal("0"))
        self.assertEqual(self.item.image.name, "items/default-item.png")

    def test_item_code_auto_generated(self):
        self.assertTrue(self.item.item_code.startswith("ITEM-"))
        self.assertEqual(len(self.item.item_code), 9)

        item2 = Item.objects.create(
            item_name="Second Item",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
        )
        num1 = int(self.item.item_code.split("-")[1])
        num2 = int(item2.item_code.split("-")[1])
        self.assertEqual(num2, num1 + 1)

    def test_department_choices(self):
        self.assertEqual(self.item.get_department_display(), "Food")
        item = Item.objects.create(
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
        self.item.is_sales_item = False
        self.item.is_purchase_item = False
        self.item.full_clean()

    def test_template_cannot_be_sales_or_purchase(self):
        self.item.has_variants = True
        self.item.is_stock_item = False
        self.item.is_sales_item = True
        with self.assertRaises(ValidationError):
            self.item.full_clean()

    def test_variant_of_without_parent_has_variants_raises(self):
        parent = Item.objects.create(
            item_name="Template",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            has_variants=False,
            is_stock_item=False,
        )
        variant = Item(
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
            item_name="Template",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            has_variants=True,
            is_stock_item=False,
        )
        variant = Item(
            item_name="Variant",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            variant_of=parent,
        )
        variant.full_clean()

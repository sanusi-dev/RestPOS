from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup
from apps.menu.models import ItemVariant, Menu, MenuItem
from apps.settings.models import Branch


class ItemVariantModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Drinks")
        cls.parent_item = Item.objects.create(
            item_code="COFFEE001",
            item_name="Coffee",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="DRINKS",
            is_sales_item=True,
        )
        cls.variant_item = Item.objects.create(
            item_code="COFFEE-L",
            item_name="Large Coffee",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="DRINKS",
            is_sales_item=True,
        )
        cls.non_menu_item = Item.objects.create(
            item_code="COFFEE-XL",
            item_name="XL Coffee",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="DRINKS",
            is_sales_item=True,
        )
        cls.menu = Menu.objects.create(name="Drink Menu", branch=cls.branch)
        MenuItem.objects.create(menu=cls.menu, item=cls.variant_item, rate=Decimal("800"))

    def test_str(self):
        variant = ItemVariant.objects.create(parent_item=self.parent_item, variant_item=self.variant_item)
        self.assertEqual(str(variant), "Coffee → Large Coffee")

    def test_create_valid(self):
        variant = ItemVariant.objects.create(parent_item=self.parent_item, variant_item=self.variant_item)
        self.assertEqual(variant.variant_item, self.variant_item)

    def test_unique_constraint(self):
        ItemVariant.objects.create(parent_item=self.parent_item, variant_item=self.variant_item)
        with self.assertRaises(IntegrityError):
            ItemVariant.objects.create(parent_item=self.parent_item, variant_item=self.variant_item)

    def test_validation_variant_must_be_in_menu(self):
        variant = ItemVariant(parent_item=self.parent_item, variant_item=self.non_menu_item)
        with self.assertRaises(ValidationError):
            variant.full_clean()

    def test_validation_passes_when_variant_in_menu(self):
        variant = ItemVariant(parent_item=self.parent_item, variant_item=self.variant_item)
        variant.full_clean()

    def test_delete(self):
        variant = ItemVariant.objects.create(parent_item=self.parent_item, variant_item=self.variant_item)
        pk = variant.pk
        variant.delete()
        self.assertFalse(ItemVariant.objects.filter(pk=pk).exists())

    def test_same_variant_different_parent(self):
        parent2 = Item.objects.create(
            item_code="TEA001",
            item_name="Tea",
            item_group=self.group,
            stock_uom=self.uom,
            department="DRINKS",
            is_sales_item=True,
        )
        ItemVariant.objects.create(parent_item=self.parent_item, variant_item=self.variant_item)
        variant2 = ItemVariant.objects.create(parent_item=parent2, variant_item=self.variant_item)
        self.assertEqual(variant2.variant_item, self.variant_item)

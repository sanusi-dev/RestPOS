from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup
from apps.menu.models import ItemVariant, Menu, MenuItem


class ItemVariantModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
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
        cls.menu = Menu.objects.create(name="Drink Menu")
        MenuItem.objects.create(menu=cls.menu, item=cls.variant_item, rate=Decimal("800"))

    def test_validation_variant_must_be_in_menu(self):
        variant = ItemVariant(parent_item=self.parent_item, variant_item=self.non_menu_item)
        with self.assertRaises(ValidationError):
            variant.full_clean()

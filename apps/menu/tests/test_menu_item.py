from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup
from apps.menu.models import Menu, MenuItem


class MenuItemModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.item_food = Item.objects.create(
            item_code="RICE001",
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_sales_item=True,
            is_stock_item=False,
            is_purchase_item=False,
            last_purchase_rate=Decimal("1200"),
        )
        cls.item_drink = Item.objects.create(
            item_code="DRINK001",
            item_name="Coke",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="DRINKS",
            is_sales_item=True,
            is_stock_item=True,
            is_purchase_item=True,
            last_purchase_rate=Decimal("300"),
        )
        cls.menu = Menu.objects.create(name="Lunch Menu")

    def test_rate_default_from_last_purchase_rate(self):
        mi = MenuItem(menu=self.menu, item=self.item_food, rate=Decimal("0"))
        mi.clean()
        self.assertEqual(mi.rate, Decimal("1200"))

    def test_non_sales_item_rejected(self):
        raw = Item.objects.create(
            item_name="Raw Rice",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            is_sales_item=False,
            is_stock_item=True,
            is_purchase_item=True,
        )
        mi = MenuItem(menu=self.menu, item=raw, rate=Decimal("100"))
        with self.assertRaises(ValidationError):
            mi.full_clean()

    def test_template_item_rejected(self):
        template = Item.objects.create(
            item_name="Size Template",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            has_variants=True,
            is_stock_item=False,
        )
        mi = MenuItem(menu=self.menu, item=template, rate=Decimal("100"))
        with self.assertRaises(ValidationError):
            mi.full_clean()


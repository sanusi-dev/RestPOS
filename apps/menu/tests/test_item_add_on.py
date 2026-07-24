from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup
from apps.menu.models import ItemAddOn, Menu, MenuItem
from apps.settings.models import Branch


class ItemAddOnModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.parent_item = Item.objects.create(
            item_code="BURGER001",
            item_name="Burger",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_sales_item=True,
        )
        cls.add_on_item = Item.objects.create(
            item_code="CHEESE001",
            item_name="Extra Cheese",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_sales_item=True,
        )
        cls.non_menu_item = Item.objects.create(
            item_code="BACON001",
            item_name="Extra Bacon",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_sales_item=True,
        )
        cls.menu = Menu.objects.create(name="Lunch Menu", branch=cls.branch)
        MenuItem.objects.create(menu=cls.menu, item=cls.add_on_item, rate=Decimal("200"))

    def test_str(self):
        add_on = ItemAddOn.objects.create(parent_item=self.parent_item, add_on_item=self.add_on_item)
        self.assertEqual(str(add_on), "Burger + Extra Cheese")

    def test_create_valid(self):
        add_on = ItemAddOn.objects.create(parent_item=self.parent_item, add_on_item=self.add_on_item)
        self.assertEqual(add_on.add_on_item, self.add_on_item)

    def test_unique_constraint(self):
        ItemAddOn.objects.create(parent_item=self.parent_item, add_on_item=self.add_on_item)
        with self.assertRaises(IntegrityError):
            ItemAddOn.objects.create(parent_item=self.parent_item, add_on_item=self.add_on_item)

    def test_validation_add_on_must_be_in_menu(self):
        add_on = ItemAddOn(parent_item=self.parent_item, add_on_item=self.non_menu_item)
        with self.assertRaises(ValidationError):
            add_on.full_clean()

    def test_validation_passes_when_add_on_in_menu(self):
        add_on = ItemAddOn(parent_item=self.parent_item, add_on_item=self.add_on_item)
        add_on.full_clean()

    def test_delete(self):
        add_on = ItemAddOn.objects.create(parent_item=self.parent_item, add_on_item=self.add_on_item)
        pk = add_on.pk
        add_on.delete()
        self.assertFalse(ItemAddOn.objects.filter(pk=pk).exists())

    def test_same_add_on_different_parent(self):
        parent2 = Item.objects.create(
            item_code="SANDWICH001",
            item_name="Sandwich",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            is_sales_item=True,
        )
        ItemAddOn.objects.create(parent_item=self.parent_item, add_on_item=self.add_on_item)
        add_on2 = ItemAddOn.objects.create(parent_item=parent2, add_on_item=self.add_on_item)
        self.assertEqual(add_on2.add_on_item, self.add_on_item)

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup
from apps.menu.models import ItemAddOn, Menu, MenuItem


class ItemAddOnModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
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
        cls.menu = Menu.objects.create(name="Lunch Menu")
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

    def test_validation_rejects_non_sellable_add_on(self):
        non_sellable = Item.objects.create(
            item_code="NOSALE001",
            item_name="Not Sellable",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            is_sales_item=False,
        )
        add_on = ItemAddOn(parent_item=self.parent_item, add_on_item=non_sellable)
        with self.assertRaises(ValidationError) as ctx:
            add_on.full_clean()
        self.assertIn("add_on_item", ctx.exception.message_dict)

    def test_validation_rejects_template_add_on(self):
        template = Item.objects.create(
            item_code="TMPL001",
            item_name="Template",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            has_variants=True,
        )
        add_on = ItemAddOn(parent_item=self.parent_item, add_on_item=template)
        with self.assertRaises(ValidationError) as ctx:
            add_on.full_clean()
        self.assertIn("add_on_item", ctx.exception.message_dict)

    def test_validation_passes_when_add_on_in_menu(self):
        add_on = ItemAddOn(parent_item=self.parent_item, add_on_item=self.add_on_item)
        add_on.full_clean()

    def test_non_sellable_item_stops_being_add_on(self):
        ItemAddOn.objects.create(parent_item=self.parent_item, add_on_item=self.add_on_item)
        self.assertTrue(ItemAddOn.objects.filter(add_on_item=self.add_on_item).exists())
        # Drop enabled menu lines so Item.clean allows turning off sellable.
        MenuItem.objects.filter(item=self.add_on_item).update(disabled=True)
        self.add_on_item.is_sales_item = False
        self.add_on_item.full_clean()
        self.add_on_item.save()
        self.assertFalse(ItemAddOn.objects.filter(add_on_item=self.add_on_item).exists())

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

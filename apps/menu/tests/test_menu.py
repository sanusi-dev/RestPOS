from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup
from apps.menu.models import Menu


class MenuModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.item1 = Item.objects.create(
            item_code="RICE001",
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_sales_item=True,
        )
        cls.item2 = Item.objects.create(
            item_code="DRINK001",
            item_name="Coke",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="DRINKS",
            is_sales_item=True,
        )
        cls.menu = Menu.objects.create(name="Lunch Menu")

    def test_str_returns_name(self):
        self.assertEqual(str(self.menu), "Lunch Menu")

    def test_default_enabled(self):
        self.assertTrue(self.menu.enabled)

    def test_name_unique(self):
        with self.assertRaises(IntegrityError):
            Menu.objects.create(name="Lunch Menu")

    def test_ordering_name(self):
        Menu.objects.create(name="Z Menu")
        menus = list(Menu.objects.values_list("name", flat=True))
        self.assertEqual(menus, ["Lunch Menu", "Z Menu"])

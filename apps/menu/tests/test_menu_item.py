from decimal import Decimal

from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup
from apps.menu.models import Menu, MenuItem
from apps.settings.models import Branch


class MenuItemModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.item_food = Item.objects.create(
            item_code="RICE001",
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            standard_rate=Decimal("1200"),
        )
        cls.item_drink = Item.objects.create(
            item_code="DRINK001",
            item_name="Coke",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="DRINKS",
            standard_rate=Decimal("300"),
        )
        cls.menu = Menu.objects.create(name="Lunch Menu", branch=cls.branch)

    def test_str_returns_item_name(self):
        mi = MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("1500"))
        self.assertEqual(str(mi), "Jollof Rice")

    def test_item_name_auto_set_from_item(self):
        mi = MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("1500"))
        self.assertEqual(mi.item_name, "Jollof Rice")

    def test_rate_default_from_standard_rate(self):
        mi = MenuItem(menu=self.menu, item=self.item_food, rate=Decimal("0"))
        mi.clean()
        self.assertEqual(mi.rate, Decimal("1200"))

    def test_default_special_dish_false(self):
        mi = MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("1500"))
        self.assertFalse(mi.special_dish)

    def test_default_disabled_false(self):
        mi = MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("1500"))
        self.assertFalse(mi.disabled)

    def test_menu_item_unique_per_menu(self):
        MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("1500"))
        with self.assertRaises(IntegrityError):
            MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("2000"))

    def test_same_item_different_menu(self):
        menu2 = Menu.objects.create(name="Dinner Menu", branch=self.branch)
        MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("1500"))
        mi2 = MenuItem.objects.create(menu=menu2, item=self.item_food, rate=Decimal("2000"))
        self.assertEqual(mi2.rate, Decimal("2000"))

    def test_disabled_item_excluded_from_price_list(self):
        mi = MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("1500"))
        pl = self.menu.price_lists.first()
        self.assertEqual(pl.prices.count(), 1)
        mi.disabled = True
        mi.save()
        pl.refresh_from_db()
        self.assertEqual(pl.prices.count(), 0)

    def test_special_dish_flag(self):
        mi = MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("1500"), special_dish=True)
        mi.refresh_from_db()
        self.assertTrue(mi.special_dish)

    def test_update_rate(self):
        mi = MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("1500"))
        mi.rate = Decimal("1800")
        mi.save()
        mi.refresh_from_db()
        self.assertEqual(mi.rate, Decimal("1800"))

    def test_delete_menu_item(self):
        mi = MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("1500"))
        pk = mi.pk
        mi.delete()
        self.assertFalse(MenuItem.objects.filter(pk=pk).exists())

    def test_ordering_by_item_name(self):
        MenuItem.objects.create(menu=self.menu, item=self.item_drink, rate=Decimal("500"))
        MenuItem.objects.create(menu=self.menu, item=self.item_food, rate=Decimal("1500"))
        names = list(MenuItem.objects.filter(menu=self.menu).values_list("item_name", flat=True))
        self.assertEqual(names, ["Coke", "Jollof Rice"])

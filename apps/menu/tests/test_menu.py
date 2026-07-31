from decimal import Decimal

from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup
from apps.menu.models import Menu, MenuItem


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

    def test_sync_price_list_creates_price_list(self):
        price_lists = self.menu.price_lists.all()
        self.assertEqual(price_lists.count(), 1)
        pl = price_lists.first()
        self.assertEqual(pl.name, "Lunch Menu")
        self.assertTrue(pl.selling)
        self.assertTrue(pl.enabled)

    def test_sync_price_list_creates_item_prices(self):
        MenuItem.objects.create(menu=self.menu, item=self.item1, rate=Decimal("1500"))
        MenuItem.objects.create(menu=self.menu, item=self.item2, rate=Decimal("500"))
        pl = self.menu.price_lists.first()
        self.assertEqual(pl.prices.count(), 2)
        ip1 = pl.prices.get(item=self.item1)
        self.assertEqual(ip1.price_list_rate, Decimal("1500"))
        self.assertEqual(ip1.uom, self.uom)

    def test_sync_price_list_excludes_disabled_items(self):
        MenuItem.objects.create(menu=self.menu, item=self.item1, rate=Decimal("1500"))
        MenuItem.objects.create(menu=self.menu, item=self.item2, rate=Decimal("500"), disabled=True)
        pl = self.menu.price_lists.first()
        self.assertEqual(pl.prices.count(), 1)
        self.assertEqual(pl.prices.first().item, self.item1)

    def test_disabling_menu_disables_price_list(self):
        self.menu.enabled = False
        self.menu.save()
        pl = self.menu.price_lists.first()
        pl.refresh_from_db()
        self.assertFalse(pl.enabled)

    def test_renaming_menu_renames_price_list(self):
        self.menu.name = "Dinner Menu"
        self.menu.save()
        pl = self.menu.price_lists.first()
        pl.refresh_from_db()
        self.assertEqual(pl.name, "Dinner Menu")

    def test_sync_price_list_replaces_existing_prices(self):
        MenuItem.objects.create(menu=self.menu, item=self.item1, rate=Decimal("1500"))
        pl = self.menu.price_lists.first()
        self.assertEqual(pl.prices.count(), 1)
        mi = MenuItem.objects.get(menu=self.menu, item=self.item1)
        mi.rate = Decimal("2000")
        mi.save()
        pl.refresh_from_db()
        self.assertEqual(pl.prices.count(), 1)
        self.assertEqual(pl.prices.first().price_list_rate, Decimal("2000"))

    def test_ordering_name(self):
        Menu.objects.create(name="Z Menu")
        menus = list(Menu.objects.values_list("name", flat=True))
        self.assertEqual(menus, ["Lunch Menu", "Z Menu"])

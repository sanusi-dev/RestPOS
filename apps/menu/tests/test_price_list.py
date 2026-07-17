from decimal import Decimal

from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup
from apps.menu.models import ItemPrice, Menu, MenuItem, PriceList
from apps.settings.models import Branch


class PriceListModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.item = Item.objects.create(
            item_code="RICE001",
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
        )
        cls.menu = Menu.objects.create(name="Lunch Menu", branch=cls.branch)

    def test_str_returns_name(self):
        pl = self.menu.price_lists.first()
        self.assertEqual(str(pl), "Lunch Menu")

    def test_name_not_unique(self):
        PriceList.objects.create(name="Custom List")
        PriceList.objects.create(name="Custom List")
        self.assertEqual(PriceList.objects.filter(name="Custom List").count(), 2)

    def test_defaults(self):
        pl = PriceList.objects.create(name="Standalone List")
        self.assertTrue(pl.enabled)
        self.assertTrue(pl.selling)
        self.assertFalse(pl.buying)

    def test_auto_creation_from_menu(self):
        pl = self.menu.price_lists.first()
        self.assertIsNotNone(pl)
        self.assertEqual(pl.menu, self.menu)
        self.assertTrue(pl.selling)
        self.assertTrue(pl.enabled)

    def test_item_price_sync_on_menu_item_create(self):
        MenuItem.objects.create(menu=self.menu, item=self.item, rate=Decimal("1500"))
        pl = self.menu.price_lists.first()
        self.assertEqual(pl.prices.count(), 1)
        ip = pl.prices.first()
        self.assertEqual(ip.price_list_rate, Decimal("1500"))
        self.assertEqual(ip.uom, self.uom)
        self.assertEqual(ip.item, self.item)

    def test_item_price_sync_on_rate_change(self):
        mi = MenuItem.objects.create(menu=self.menu, item=self.item, rate=Decimal("1500"))
        mi.rate = Decimal("2000")
        mi.save()
        pl = self.menu.price_lists.first()
        self.assertEqual(pl.prices.count(), 1)
        self.assertEqual(pl.prices.first().price_list_rate, Decimal("2000"))

    def test_item_price_unique_constraint(self):
        pl = self.menu.price_lists.first()
        ItemPrice.objects.create(item=self.item, price_list=pl, price_list_rate=Decimal("1500"), uom=self.uom)
        with self.assertRaises(IntegrityError):
            ItemPrice.objects.create(item=self.item, price_list=pl, price_list_rate=Decimal("2000"), uom=self.uom)

    def test_price_list_enabled_follows_menu(self):
        self.menu.enabled = False
        self.menu.save()
        pl = self.menu.price_lists.first()
        pl.refresh_from_db()
        self.assertFalse(pl.enabled)

    def test_price_list_disabled_then_re_enabled(self):
        self.menu.enabled = False
        self.menu.save()
        self.menu.enabled = True
        self.menu.save()
        pl = self.menu.price_lists.first()
        pl.refresh_from_db()
        self.assertTrue(pl.enabled)

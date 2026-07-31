from decimal import Decimal

from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup, Warehouse
from apps.menu.models import Menu, MenuItem
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import ProductionUnit, Restaurant

from ..models import Order


class KOTTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(company="Test Co")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group_food = ItemGroup.objects.create(name="Food")
        cls.group_drinks = ItemGroup.objects.create(name="Beverages")
        cls.warehouse = Warehouse.objects.create(name="Kitchen")
        cls.food_item = Item.objects.create(
            item_name="Jollof Rice", item_group=cls.group_food, stock_uom=cls.uom, department="FOOD", is_sales_item=True
        )
        cls.drink_item = Item.objects.create(
            item_name="Coke", item_group=cls.group_drinks, stock_uom=cls.uom, department="DRINKS", is_sales_item=True
        )
        cls.menu = Menu.objects.create(name="Main Menu")
        MenuItem.objects.create(menu=cls.menu, item=cls.food_item, rate=Decimal("1500"))
        MenuItem.objects.create(menu=cls.menu, item=cls.drink_item, rate=Decimal("500"))
        cls.cash = ModeOfPayment.objects.get(name="Cash")
        PaymentGLMapping.objects.create(mode_of_payment=cls.cash, default_account="Cash Account")
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.default_warehouse = cls.warehouse
        cls.restaurant.save()
        cls.kitchen = ProductionUnit.objects.create(name="Kitchen", warehouse=cls.warehouse, department="FOOD")
        cls.bar = ProductionUnit.objects.create(name="Bar", warehouse=cls.warehouse, department="DRINKS")


class KOTGenerationTest(KOTTestBase):
    def setUp(self):
        self.order = Order.objects.create()

    def test_generate_kot_new_order(self):
        self.order.add_item(self.food_item, qty=2, rate=Decimal("1500"))
        kots = self.order.generate_kots([])
        self.assertEqual(len(kots), 1)
        kot = kots[0]
        self.assertEqual(kot.type, "New Order")
        self.assertEqual(kot.production_unit, self.kitchen)
        self.assertEqual(kot.items.count(), 1)
        self.assertEqual(kot.items.first().qty, Decimal("2"))

    def test_generate_kot_modified_order(self):
        self.order.add_item(self.food_item, qty=1, rate=Decimal("1500"))
        self.order.generate_kots([])
        self.order.add_item(self.food_item, qty=1, rate=Decimal("1500"))
        prev = [{"item_id": self.food_item.pk, "qty": "1", "customer_index": 1, "comments": ""}]
        kots = self.order.generate_kots(prev)
        self.assertEqual(len(kots), 1)
        self.assertEqual(kots[0].type, "Order Modified")
        self.assertEqual(kots[0].items.first().qty, Decimal("1"))

    def test_no_kot_when_unchanged(self):
        self.order.add_item(self.food_item, qty=2, rate=Decimal("1500"))
        prev = [{"item_id": self.food_item.pk, "qty": "2", "customer_index": 1, "comments": ""}]
        kots = self.order.generate_kots(prev)
        self.assertEqual(len(kots), 0)

    def test_department_routing_food_to_kitchen(self):
        self.order.add_item(self.food_item, qty=1, rate=Decimal("1500"))
        kots = self.order.generate_kots([])
        self.assertEqual(len(kots), 1)
        self.assertEqual(kots[0].production_unit, self.kitchen)

    def test_department_routing_drinks_to_bar(self):
        self.order.add_item(self.drink_item, qty=1, rate=Decimal("500"))
        kots = self.order.generate_kots([])
        self.assertEqual(len(kots), 1)
        self.assertEqual(kots[0].production_unit, self.bar)

    def test_department_routing_both_creates_two_kots(self):
        self.order.add_item(self.food_item, qty=1, rate=Decimal("1500"))
        self.order.add_item(self.drink_item, qty=1, rate=Decimal("500"))
        kots = self.order.generate_kots([])
        self.assertEqual(len(kots), 2)
        pu_names = {k.production_unit.name for k in kots}
        self.assertEqual(pu_names, {"Kitchen", "Bar"})

    def test_partially_cancelled_kot(self):
        self.order.add_item(self.food_item, qty=2, rate=Decimal("1500"))
        self.order.generate_kots([])
        oi = self.order.items.first()
        oi.qty = Decimal("1")
        oi.save()
        prev = [{"item_id": self.food_item.pk, "qty": "2", "customer_index": 1, "comments": ""}]
        kots = self.order.generate_kots(prev)
        self.assertEqual(len(kots), 1)
        kot = kots[0]
        self.assertEqual(kot.type, "Partially Cancelled")
        self.assertTrue(kot.original_kots)
        ki = kot.items.first()
        self.assertEqual(ki.cancelled_qty, Decimal("1"))

    def test_customer_index_grouping(self):
        order = Order.objects.create(guest_count=2)
        order.add_item(self.food_item, qty=1, rate=Decimal("1500"), customer_index=1)
        order.add_item(self.food_item, qty=1, rate=Decimal("1500"), customer_index=2)
        kots = order.generate_kots([])
        self.assertEqual(len(kots), 1)
        kot = kots[0]
        self.assertEqual(kot.items.count(), 2)
        indices = {ki.customer_index for ki in kot.items.all()}
        self.assertEqual(indices, {1, 2})

    def test_kot_number_format(self):
        self.order.add_item(self.food_item, qty=1, rate=Decimal("1500"))
        kots = self.order.generate_kots([])
        self.assertTrue(kots[0].kot_number.startswith("KOT-"))

    def test_cancel_kot_number_format(self):
        self.order.add_item(self.food_item, qty=2, rate=Decimal("1500"))
        self.order.generate_kots([])
        oi = self.order.items.first()
        oi.qty = Decimal("1")
        oi.save()
        prev = [{"item_id": self.food_item.pk, "qty": "2", "customer_index": 1, "comments": ""}]
        kots = self.order.generate_kots(prev)
        cancel_kot = kots[0]
        self.assertTrue(cancel_kot.kot_number.startswith("CNCL-KOT-"))

    def test_generate_kots_no_production_unit_skips(self):
        self.kitchen.delete()
        self.order.add_item(self.food_item, qty=1, rate=Decimal("1500"))
        kots = self.order.generate_kots([])
        self.assertEqual(len(kots), 0)

    def test_removed_item_generates_cancel_kot(self):
        self.order.add_item(self.food_item, qty=2, rate=Decimal("1500"))
        self.order.generate_kots([])
        oi = self.order.items.first()
        oi.delete()
        prev = [{"item_id": self.food_item.pk, "qty": "2", "customer_index": 1, "comments": ""}]
        kots = self.order.generate_kots(prev)
        self.assertEqual(len(kots), 1)
        self.assertEqual(kots[0].type, "Partially Cancelled")

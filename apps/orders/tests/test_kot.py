from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import UOM, Bin, Item, ItemGroup, Warehouse
from apps.menu.models import Menu, MenuItem
from apps.payments.models import ModeOfPayment
from apps.settings.models import ProductionUnit, Restaurant

from ..models import Order
from ..services import add_order_line, cancel_order, create_tickets, remove_order_line
from .accounting_setup import OrderAccountingMixin


class KOTTestBase(OrderAccountingMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(company="Test Co")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group_food = ItemGroup.objects.create(name="Food")
        cls.group_drinks = ItemGroup.objects.create(name="Beverages")
        cls.kitchen_warehouse = Warehouse.objects.create(name="Kitchen")
        cls.bar_warehouse = Warehouse.objects.create(name="Bar")
        cls.food_item = Item.objects.create(
            item_name="Jollof Rice", item_group=cls.group_food, stock_uom=cls.uom, department="FOOD", is_sales_item=True
        )
        cls.drink_item = Item.objects.create(
            item_name="Coke", item_group=cls.group_drinks, stock_uom=cls.uom, department="DRINKS", is_sales_item=True
        )
        cls.menu = Menu.objects.create(name="Main Menu")
        MenuItem.objects.create(menu=cls.menu, item=cls.food_item, rate=Decimal("1500"))
        MenuItem.objects.create(menu=cls.menu, item=cls.drink_item, rate=Decimal("500"))
        cls.cash, _ = ModeOfPayment.objects.get_or_create(name="Cash", defaults={"type": "CASH"})
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.default_warehouse = cls.bar_warehouse
        cls.restaurant.save()
        cls._setup_accounting()
        cls.kitchen = ProductionUnit.objects.create(name="Kitchen", warehouse=cls.kitchen_warehouse, department="FOOD")
        cls.bar = ProductionUnit.objects.create(name="Bar", warehouse=cls.bar_warehouse, department="DRINKS")
        Bin.objects.create(item=cls.drink_item, warehouse=cls.bar_warehouse, actual_qty=Decimal("100"))


class KOTGenerationTest(KOTTestBase):
    def setUp(self):
        self.order = Order.objects.create()

    def test_generate_kot_new_order(self):
        add_order_line(self.order, self.food_item, qty=2, rate=Decimal("1500"))
        kots = create_tickets(
            self.order,
        )
        self.assertEqual(len(kots), 1)
        kot = kots[0]
        self.assertEqual(kot.type, "New Order")
        self.assertEqual(kot.ticket_type, "kitchen")
        self.assertEqual(kot.print_status, "PENDING")
        self.assertEqual(kot.production_unit, self.kitchen)
        self.assertEqual(kot.items.count(), 1)
        self.assertEqual(kot.items.first().qty, Decimal("2"))

    def test_sent_order_cannot_be_modified(self):
        add_order_line(self.order, self.food_item, qty=1, rate=Decimal("1500"))
        create_tickets(
            self.order,
        )
        with self.assertRaises(ValidationError):
            add_order_line(self.order, self.food_item, qty=1, rate=Decimal("1500"))

    def test_second_send_is_rejected(self):
        add_order_line(self.order, self.food_item, qty=2, rate=Decimal("1500"))
        create_tickets(
            self.order,
        )
        with self.assertRaises(ValidationError):
            create_tickets(
                self.order,
            )

    def test_department_routing_food_to_kitchen(self):
        add_order_line(self.order, self.food_item, qty=1, rate=Decimal("1500"))
        kots = create_tickets(
            self.order,
        )
        self.assertEqual(len(kots), 1)
        self.assertEqual(kots[0].production_unit, self.kitchen)

    def test_department_routing_drinks_to_bar(self):
        add_order_line(self.order, self.drink_item, qty=1, rate=Decimal("500"))
        kots = create_tickets(
            self.order,
        )
        self.assertEqual(len(kots), 1)
        self.assertEqual(kots[0].ticket_type, "bar")
        self.assertTrue(kots[0].kot_number.startswith("BOT-"))
        self.assertEqual(kots[0].production_unit, self.bar)

    def test_department_routing_both_creates_two_kots(self):
        add_order_line(self.order, self.food_item, qty=1, rate=Decimal("1500"))
        add_order_line(self.order, self.drink_item, qty=1, rate=Decimal("500"))
        kots = create_tickets(
            self.order,
        )
        self.assertEqual(len(kots), 2)
        pu_names = {k.production_unit.name for k in kots}
        self.assertEqual(pu_names, {"Kitchen", "Bar"})
        self.assertEqual({k.ticket_type for k in kots}, {"kitchen", "bar"})

    def test_mixed_order_requires_all_production_units(self):
        self.bar.delete()
        add_order_line(self.order, self.food_item, qty=1, rate=Decimal("1500"))
        add_order_line(self.order, self.drink_item, qty=1, rate=Decimal("500"))
        with self.assertRaises(ValidationError):
            create_tickets(
                self.order,
            )
        self.assertEqual(self.order.kots.count(), 0)

    def test_takeaway_blocked_department_is_not_ticketed(self):
        self.bar.block_takeaway_kot = True
        self.bar.save(update_fields=["block_takeaway_kot"])
        order = Order.objects.create(order_type="TAKE_AWAY")
        add_order_line(order, self.food_item, qty=1, rate=Decimal("1500"))
        add_order_line(order, self.drink_item, qty=1, rate=Decimal("500"))
        kots = create_tickets(
            order,
        )
        self.assertEqual(len(kots), 1)
        self.assertEqual(kots[0].ticket_type, "kitchen")

    def test_sent_order_cannot_reduce_item_quantity(self):
        add_order_line(self.order, self.food_item, qty=2, rate=Decimal("1500"))
        create_tickets(
            self.order,
        )
        oi = self.order.items.first()
        with self.assertRaises(ValidationError):
            remove_order_line(self.order, oi.pk)

    def test_customer_index_grouping(self):
        order = Order.objects.create(guest_count=2)
        add_order_line(order, self.food_item, qty=1, rate=Decimal("1500"), customer_index=1)
        add_order_line(order, self.food_item, qty=1, rate=Decimal("1500"), customer_index=2)
        kots = create_tickets(
            order,
        )
        self.assertEqual(len(kots), 1)
        kot = kots[0]
        self.assertEqual(kot.items.count(), 2)
        indices = {ki.customer_index for ki in kot.items.all()}
        self.assertEqual(indices, {1, 2})

    def test_kot_number_format(self):
        add_order_line(self.order, self.food_item, qty=1, rate=Decimal("1500"))
        kots = create_tickets(
            self.order,
        )
        self.assertTrue(kots[0].kot_number.startswith("KOT-"))

    def test_cancel_kot_number_format(self):
        add_order_line(self.order, self.food_item, qty=2, rate=Decimal("1500"))
        create_tickets(
            self.order,
        )
        cancel_order(self.order, "Test reason")
        cancel_kot = self.order.kots.filter(type="Cancelled").first()
        self.assertTrue(cancel_kot.kot_number.startswith("CNCL-KOT-"))

    def test_generate_kots_no_production_unit_skips(self):
        self.kitchen.delete()
        add_order_line(self.order, self.food_item, qty=1, rate=Decimal("1500"))
        with self.assertRaises(ValidationError):
            create_tickets(
                self.order,
            )

    def test_sent_order_cannot_remove_item(self):
        add_order_line(self.order, self.food_item, qty=2, rate=Decimal("1500"))
        create_tickets(
            self.order,
        )
        oi = self.order.items.first()
        with self.assertRaises(ValidationError):
            remove_order_line(self.order, oi.pk)

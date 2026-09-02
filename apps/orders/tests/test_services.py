"""Direct service-level tests for order workflows — no HTTP, no templates."""

from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import UOM, Bin, Item, ItemGroup, Warehouse
from apps.menu.models import Menu, MenuItem
from apps.orders.models import KOT_PRINT_PENDING, KOT_PRINTED, TAKE_AWAY, Order
from apps.payments.models import ModeOfPayment
from apps.settings.models import ProductionUnit, Restaurant
from apps.staff.models import OpeningPayment, POSOpeningEntry
from apps.users.models import CustomUser

from ..services import (
    add_order_line,
    create_draft_order,
    create_tickets,
    dispatch_tickets,
    drink_stock_available,
    update_order_item,
    update_order_meta,
)
from .accounting_setup import OrderAccountingMixin


class OrderServiceTestBase(OrderAccountingMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(company="Test Co")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group_food = ItemGroup.objects.create(name="Food")
        cls.group_drinks = ItemGroup.objects.create(name="Beverages")
        cls.warehouse = Warehouse.objects.create(name="Kitchen")
        cls.item = Item.objects.create(
            item_name="Jollof Rice",
            item_group=cls.group_food,
            stock_uom=cls.uom,
            department="FOOD",
            is_sales_item=True,
            is_stock_item=False,
            is_purchase_item=False,
        )
        cls.item2 = Item.objects.create(
            item_name="Coke",
            item_group=cls.group_drinks,
            stock_uom=cls.uom,
            department="DRINKS",
            is_sales_item=True,
            is_stock_item=True,
            is_purchase_item=True,
        )
        cls.menu = Menu.objects.create(name="Main Menu")
        cls.menu_item = MenuItem.objects.create(menu=cls.menu, item=cls.item, rate=Decimal("1500"))
        cls.menu_item2 = MenuItem.objects.create(menu=cls.menu, item=cls.item2, rate=Decimal("500"))
        Bin.objects.create(item=cls.item, warehouse=cls.warehouse, actual_qty=Decimal("100"))
        Bin.objects.create(item=cls.item2, warehouse=cls.warehouse, actual_qty=Decimal("100"))
        cls.cash, _ = ModeOfPayment.objects.get_or_create(name="Cash", defaults={"type": "CASH"})
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.default_warehouse = cls.warehouse
        cls.restaurant.save()
        cls._setup_accounting()
        cls.user = CustomUser.objects.create_user(username="cashier", password="testpass123")
        cls.opening = POSOpeningEntry.objects.create(cashier=cls.user)
        OpeningPayment.objects.create(
            opening_entry=cls.opening,
            mode_of_payment=cls.cash,
            opening_amount=Decimal("50000"),
        )
        cls.opening.submit()
        cls.kitchen = ProductionUnit.objects.create(name="Kitchen", warehouse=cls.warehouse, department="FOOD")
        cls.bar = ProductionUnit.objects.create(name="Bar", warehouse=cls.warehouse, department="DRINKS")

    def _create_order(self, **kwargs):
        defaults = {"opening_entry": self.opening}
        defaults.update(kwargs)
        return Order.objects.create(**defaults)


class CreateDraftOrderTest(OrderServiceTestBase):
    def test_creates_draft_with_number_and_audit(self):
        order = create_draft_order(self.opening, self.user, order_type=TAKE_AWAY, guest_count=3)
        self.assertEqual(order.status, "DRAFT")
        self.assertEqual(order.order_type, TAKE_AWAY)
        self.assertEqual(order.guest_count, 3)
        self.assertIsNotNone(order.order_number)
        self.assertEqual(order.invoice_number, f"REST-{order.pk}")
        self.assertTrue(order.audit_events.filter(event_type="CREATED", actor=self.user).exists())

    def test_draft_cap_blocks_new_order(self):
        self.restaurant.max_open_drafts = 2
        self.restaurant.save()
        create_draft_order(self.opening, self.user)
        create_draft_order(self.opening, self.user)
        with self.assertRaisesMessage(ValidationError, "already has 2 open drafts"):
            create_draft_order(self.opening, self.user)

    def test_no_open_shift_raises(self):
        cancelled = POSOpeningEntry.objects.create(cashier=self.user)
        cancelled.cancel(by_user=self.user)
        with self.assertRaisesMessage(ValidationError, "Open a shift before taking orders."):
            create_draft_order(cancelled, self.user)

    def test_missing_settings_raises(self):
        Restaurant.objects.all().delete()
        with self.assertRaisesMessage(ValidationError, "Restaurant settings are not configured."):
            create_draft_order(self.opening, self.user)


class UpdateOrderMetaTest(OrderServiceTestBase):
    def test_changes_order_type_and_audits(self):
        order = self._create_order()
        result = update_order_meta(order, order_type=TAKE_AWAY, actor=self.user)
        order.refresh_from_db()
        self.assertEqual(order.order_type, TAKE_AWAY)
        self.assertTrue(order.audit_events.filter(event_type="ORDER_TYPE_CHANGED").exists())
        self.assertEqual(result, 1)

    def test_invalid_order_type_raises(self):
        order = self._create_order()
        with self.assertRaisesMessage(ValidationError, "Choose a valid order type."):
            update_order_meta(order, order_type="ROOM_SERVICE", actor=self.user)

    def test_guest_delta_increments(self):
        order = self._create_order()
        result = update_order_meta(order, guest_delta="2", actor=self.user)
        order.refresh_from_db()
        self.assertEqual(order.guest_count, 3)
        self.assertEqual(result, 3)
        self.assertTrue(order.audit_events.filter(event_type="GUEST_COUNT_CHANGED", metadata__guest_count=3).exists())

    def test_absolute_guest_count(self):
        order = self._create_order()
        update_order_meta(order, guest_count="5", actor=self.user)
        order.refresh_from_db()
        self.assertEqual(order.guest_count, 5)

    def test_guest_count_clamped(self):
        order = self._create_order()
        update_order_meta(order, guest_count="99", actor=self.user)
        order.refresh_from_db()
        self.assertEqual(order.guest_count, 50)

    def test_lowering_below_guest_with_items_raises(self):
        order = self._create_order(guest_count=2)
        add_order_line(order, self.item, qty=1, customer_index=2, rate=Decimal("1500"))
        with self.assertRaises(ValidationError):
            update_order_meta(order, guest_count="1", actor=self.user)
        order.refresh_from_db()
        self.assertEqual(order.guest_count, 2)

    def test_legacy_printed_draft_remains_editable(self):
        order = self._create_order()
        order.invoice_printed = True
        order.save(update_fields=["invoice_printed"])
        result = update_order_meta(order, guest_delta="1", actor=self.user)
        order.refresh_from_db()
        self.assertEqual(order.guest_count, 2)
        self.assertEqual(result, 2)

    def test_sent_order_rejects_edits(self):
        order = self._create_order()
        add_order_line(order, self.item, qty=1, rate=Decimal("1500"))
        create_tickets(order, created_by=self.user)
        with self.assertRaisesMessage(
            ValidationError, "This order was sent to the kitchen or bar. Cancel it before making changes."
        ):
            update_order_meta(order, guest_delta="1", actor=self.user)

    def test_no_params_is_a_noop(self):
        order = self._create_order()
        result = update_order_meta(order, actor=self.user)
        self.assertEqual(result, 1)
        self.assertFalse(order.audit_events.exists())


class UpdateOrderItemTest(OrderServiceTestBase):
    def _order_with_drink(self):
        order = self._create_order()
        add_order_line(order, self.item2, qty=2, rate=Decimal("500"))
        return order

    def test_increment(self):
        order = self._order_with_drink()
        update_order_item(order, order.items.get().pk, action="increment", actor=self.user)
        line = order.items.get()
        self.assertEqual(line.qty, Decimal("3"))
        self.assertTrue(order.audit_events.filter(event_type="ITEM_QUANTITY_CHANGED").exists())

    def test_remove_deletes_line_and_audits(self):
        order = self._order_with_drink()
        line = order.items.get()
        update_order_item(order, line.pk, action="remove", actor=self.user)
        self.assertFalse(order.items.exists())
        audit = order.audit_events.get(event_type="ITEM_REMOVED")
        self.assertEqual(audit.metadata["item_id"], self.item2.pk)

    def test_set_quantity(self):
        order = self._order_with_drink()
        update_order_item(order, order.items.get().pk, action="update", qty="4", actor=self.user)
        self.assertEqual(order.items.get().qty, Decimal("4"))

    def test_missing_line_raises(self):
        order = self._order_with_drink()
        with self.assertRaisesMessage(ValidationError, "That order line no longer exists."):
            update_order_item(order, 999999, action="increment", actor=self.user)


class DispatchTicketsTest(OrderServiceTestBase):
    def _sent_ticket(self):
        order = self._create_order()
        add_order_line(order, self.item2, qty=1, rate=Decimal("500"))
        return create_tickets(order, created_by=self.user)[0]

    def test_success_marks_printed(self):
        ticket = self._sent_ticket()
        failures = dispatch_tickets([ticket])
        self.assertEqual(failures, [])
        ticket.refresh_from_db()
        self.assertEqual(ticket.print_status, KOT_PRINTED)

    def test_failure_stays_pending_and_reports_type(self):
        ticket = self._sent_ticket()
        with patch(
            "apps.orders.services.printing.print_ticket",
            return_value=type("R", (), {"success": False, "ticket_type": "bar"})(),
        ):
            failures = dispatch_tickets([ticket])
        self.assertEqual(failures, ["bar"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.print_status, KOT_PRINT_PENDING)


class DrinkStockAvailableTest(OrderServiceTestBase):
    def test_out_of_stock_marking(self):
        Bin.objects.filter(item=self.item2).update(actual_qty=Decimal("0"))
        menu_items = [self.menu_item2]
        drink_stock_available(menu_items, self.restaurant)
        self.assertTrue(menu_items[0].stock_unavailable)
        self.assertEqual(menu_items[0].stock_message, "Out of stock")

    def test_non_stock_drink_requires_setup(self):
        self.item2.is_stock_item = False
        self.item2.save()
        menu_items = [self.menu_item2]
        drink_stock_available(menu_items, self.restaurant)
        self.assertTrue(menu_items[0].stock_unavailable)
        self.assertIn("stock-tracked, sellable, and purchasable", menu_items[0].stock_message)

    def test_food_items_never_marked(self):
        self.item2.is_stock_item = False
        self.item2.save()
        menu_items = [self.menu_item, self.menu_item2]
        drink_stock_available(menu_items, self.restaurant)
        self.assertFalse(menu_items[0].stock_unavailable)

    def test_missing_warehouse_requires_setup(self):
        self.restaurant.default_warehouse = None
        self.restaurant.save()
        menu_items = [self.menu_item2]
        drink_stock_available(menu_items, self.restaurant)
        self.assertTrue(menu_items[0].stock_unavailable)
        self.assertIn("configure the Bar/POS warehouse", menu_items[0].stock_message)

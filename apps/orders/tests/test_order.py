from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.inventory.models import UOM, Bin, Item, ItemGroup, StockLedgerEntry, Warehouse
from apps.menu.models import Menu, MenuItem
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import ProductionUnit, Restaurant

from ..models import Order

CustomUser = get_user_model()


class OrderTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(company="Test Co")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group_food = ItemGroup.objects.create(name="Food")
        cls.group_drinks = ItemGroup.objects.create(name="Beverages")
        cls.warehouse = Warehouse.objects.create(name="Kitchen")
        cls.item = Item.objects.create(
            item_name="Jollof Rice", item_group=cls.group_food, stock_uom=cls.uom, department="FOOD", is_sales_item=True
        )
        cls.item2 = Item.objects.create(
            item_name="Coke", item_group=cls.group_drinks, stock_uom=cls.uom, department="DRINKS", is_sales_item=True
        )
        cls.menu = Menu.objects.create(name="Main Menu")
        cls.menu_item = MenuItem.objects.create(menu=cls.menu, item=cls.item, rate=Decimal("1500"))
        cls.menu_item2 = MenuItem.objects.create(menu=cls.menu, item=cls.item2, rate=Decimal("500"))
        cls.cash = ModeOfPayment.objects.get(name="Cash")
        PaymentGLMapping.objects.create(mode_of_payment=cls.cash, default_account="Cash Account")
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.default_warehouse = cls.warehouse
        cls.restaurant.save()
        cls.kitchen = ProductionUnit.objects.create(name="Kitchen", warehouse=cls.warehouse, department="FOOD")
        cls.bar = ProductionUnit.objects.create(name="Bar", warehouse=cls.warehouse, department="DRINKS")
        cls.user = CustomUser.objects.create_user(username="cashier", password="testpass123")

    def _create_order(self, **kwargs):
        defaults = {}
        defaults.update(kwargs)
        return Order.objects.create(**defaults)

    def _create_and_print_order(self, **kwargs):
        order = self._create_order(**kwargs)
        order.invoice_printed = True
        order.save(update_fields=["invoice_printed"])
        return order


class OrderModelTest(OrderTestBase):
    def test_create_order(self):
        order = self._create_order()
        self.assertEqual(order.status, "DRAFT")
        self.assertTrue(order.invoice_number.startswith("REST-"))

    def test_order_number_assignment(self):
        order = self._create_order()
        order.assign_order_number()
        self.assertEqual(order.order_number, 1)
        order2 = self._create_order()
        order2.assign_order_number()
        self.assertEqual(order2.order_number, 2)

    def test_guest_count_defaults_to_one(self):
        order = self._create_order()
        self.assertEqual(order.guest_count, 1)

    def test_str(self):
        order = self._create_order()
        self.assertIn(order.customer_name, str(order))

    def test_arrived_time_set_on_creation(self):
        order = self._create_order()
        self.assertIsNotNone(order.arrived_time)


class OrderItemTest(OrderTestBase):
    def test_add_item(self):
        order = self._create_order()
        order.add_item(self.item, qty=2, rate=Decimal("1500"))
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().qty, Decimal("2"))

    def test_add_item_increments_existing(self):
        order = self._create_order()
        order.add_item(self.item, qty=1, rate=Decimal("1500"))
        order.add_item(self.item, qty=1, rate=Decimal("1500"))
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().qty, Decimal("2"))

    def test_different_comments_creates_separate_line(self):
        order = self._create_order()
        order.add_item(self.item, qty=1, rate=Decimal("1500"), comments="Extra spicy")
        order.add_item(self.item, qty=1, rate=Decimal("1500"), comments="No spice")
        self.assertEqual(order.items.count(), 2)

    def test_different_customer_index_creates_separate_line(self):
        order = self._create_order()
        order.add_item(self.item, qty=1, rate=Decimal("1500"), customer_index=1)
        order.add_item(self.item, qty=1, rate=Decimal("1500"), customer_index=2)
        self.assertEqual(order.items.count(), 2)

    def test_item_auto_fills_fields(self):
        order = self._create_order()
        order.add_item(self.item, qty=1, rate=Decimal("1500"))
        oi = order.items.first()
        self.assertEqual(oi.item_name, "Jollof Rice")

    def test_item_amount_calculation(self):
        order = self._create_order()
        order.add_item(self.item, qty=3, rate=Decimal("1500"))
        oi = order.items.first()
        self.assertEqual(oi.amount, Decimal("4500.00"))

    def test_remove_item(self):
        order = self._create_order()
        order.add_item(self.item, qty=1, rate=Decimal("1500"))
        oi_pk = order.items.first().pk
        order.remove_item(oi_pk)
        self.assertEqual(order.items.count(), 0)

    def test_cannot_add_to_submitted_order(self):
        from django.core.exceptions import ValidationError

        order = self._create_and_print_order()
        order.add_item(self.item, qty=1, rate=Decimal("1500"))
        order.settle([{"mode_of_payment": self.cash.pk, "amount": "1500"}])
        with self.assertRaises(ValidationError):
            order.add_item(self.item, qty=1, rate=Decimal("1500"))


class OrderSettleTest(OrderTestBase):
    def setUp(self):
        self.order = self._create_and_print_order()
        self.order.add_item(self.item, qty=2, rate=Decimal("1500"))

    def test_settle_changes_status(self):
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "3000"}])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "SUBMITTED")
        self.assertTrue(self.order.is_paid)

    def test_settle_creates_payments(self):
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "3000"}])
        self.assertEqual(self.order.payments.count(), 1)
        self.assertEqual(self.order.payments.first().amount, Decimal("3000"))

    def test_settle_computes_change(self):
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "5000"}])
        self.order.refresh_from_db()
        self.assertTrue(self.order.change_amount > 0)

    def test_settle_rejects_underpayment(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "1000"}])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "DRAFT")

    def test_settle_deducts_stock(self):
        Bin.objects.create(item=self.item, warehouse=self.warehouse, actual_qty=Decimal("10"))
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "3000"}])
        sles = StockLedgerEntry.objects.filter(voucher_type="POS Order", voucher_no=str(self.order.pk))
        self.assertTrue(sles.exists())
        self.assertEqual(sles.first().actual_qty, Decimal("-2"))

    def test_settle_skips_non_stock_items(self):
        self.item2.is_stock_item = False
        self.item2.save()
        self.order.add_item(self.item2, qty=1, rate=Decimal("500"))
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "3500"}])
        sles = StockLedgerEntry.objects.filter(voucher_type="POS Order", voucher_no=str(self.order.pk))
        self.assertEqual(sles.count(), 1)

    def test_settle_dine_in_requires_print(self):
        from django.core.exceptions import ValidationError

        order = self._create_order()
        order.add_item(self.item, qty=1, rate=Decimal("1500"))
        with self.assertRaises(ValidationError):
            order.settle([{"mode_of_payment": self.cash.pk, "amount": "1500"}])

    def test_settle_takeaway_no_print_required(self):
        order = self._create_order(order_type="TAKE_AWAY")
        order.add_item(self.item, qty=1, rate=Decimal("1500"))
        order.settle([{"mode_of_payment": self.cash.pk, "amount": "1500"}])
        self.assertEqual(order.status, "SUBMITTED")

    def test_settle_assigns_order_number(self):
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "3000"}])
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.order_number)


class OrderCancelTest(OrderTestBase):
    def setUp(self):
        self.order = self._create_and_print_order()
        self.order.add_item(self.item, qty=2, rate=Decimal("1500"))
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "3000"}])

    def test_cancel_creates_reversal_sle(self):
        self.order.cancel("Test reason")
        sles = StockLedgerEntry.objects.filter(voucher_type="POS Order Cancellation", voucher_no=str(self.order.pk))
        self.assertTrue(sles.exists())
        self.assertEqual(sles.first().actual_qty, Decimal("2"))

    def test_cancel_sets_status(self):
        self.order.cancel("Test reason")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "CANCELLED")
        self.assertEqual(self.order.cancel_reason, "Test reason")

    def test_cancel_requires_reason(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.order.cancel("")

    def test_cancel_creates_cancel_kot(self):
        from apps.settings.models import ProductionUnit

        ProductionUnit.objects.create(name="Kitchen2", warehouse=self.warehouse, department="FOOD")
        self.order.generate_kots([])
        self.order.cancel("Test reason")
        cancel_kots = self.order.kots.filter(type="Cancelled")
        self.assertTrue(cancel_kots.exists())


class OrderRecalculateTest(OrderTestBase):
    def test_recalculate_updates_net_total(self):
        order = self._create_order()
        order.add_item(self.item, qty=2, rate=Decimal("1500"))
        order.recalculate_totals()
        self.assertEqual(order.net_total, Decimal("3000.00"))

    def test_recalculate_updates_grand_total(self):
        order = self._create_order()
        order.add_item(self.item, qty=2, rate=Decimal("1500"))
        order.recalculate_totals()
        self.assertEqual(order.grand_total, Decimal("3000.00"))

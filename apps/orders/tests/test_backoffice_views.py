from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.inventory.models import UOM, Bin, Item, ItemGroup, Warehouse
from apps.menu.models import Menu, MenuItem
from apps.orders.models import Order
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import ProductionUnit, Restaurant
from apps.staff.models import OpeningPayment, POSOpeningEntry

CustomUser = get_user_model()


class BackofficeViewTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(company="Test Co")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group_food = ItemGroup.objects.create(name="Food")
        cls.warehouse = Warehouse.objects.create(name="Kitchen")
        cls.food_item = Item.objects.create(
            item_name="Jollof Rice", item_group=cls.group_food, stock_uom=cls.uom, department="FOOD", is_sales_item=True
        )
        cls.menu = Menu.objects.create(name="Main Menu")
        MenuItem.objects.create(menu=cls.menu, item=cls.food_item, rate=Decimal("1500"))
        cls.cash, _ = ModeOfPayment.objects.get_or_create(name="Cash", defaults={"type": "CASH"})
        PaymentGLMapping.objects.get_or_create(mode_of_payment=cls.cash, defaults={"default_account": "Cash Account"})
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.default_warehouse = cls.warehouse
        cls.restaurant.save()
        ProductionUnit.objects.create(name="Kitchen", warehouse=cls.warehouse, department="FOOD")
        cls.manager = CustomUser.objects.create_user(
            username="manager", password="testpass123", is_staff=True, is_superuser=True
        )
        cls.cashier_user = CustomUser.objects.create_user(username="cashier2", password="testpass123")
        cls.opening = POSOpeningEntry.objects.create(cashier=cls.manager)
        OpeningPayment.objects.create(
            opening_entry=cls.opening,
            mode_of_payment=cls.cash,
            opening_amount=Decimal("50000"),
        )
        cls.opening.submit()
        Bin.objects.create(item=cls.food_item, warehouse=cls.warehouse, actual_qty=Decimal("100"))

    def setUp(self):
        self.client.force_login(self.manager)

    def _create_order(self, **kwargs):
        defaults = {"opening_entry": self.opening}
        defaults.update(kwargs)
        return Order.objects.create(**defaults)


class OrderListTest(BackofficeViewTestBase):
    def test_order_list(self):
        self._create_order()
        response = self.client.get(reverse("orders:order_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Orders")

    def test_order_list_search(self):
        self._create_order(customer_name="John Doe")
        response = self.client.get(reverse("orders:order_list"), {"search": "John"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "John Doe")

    def test_order_list_status_filter(self):
        self._create_order()
        response = self.client.get(reverse("orders:order_list"), {"status": "DRAFT"})
        self.assertEqual(response.status_code, 200)

    def test_order_list_empty(self):
        response = self.client.get(reverse("orders:order_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No orders found")

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(reverse("orders:order_list"))
        self.assertEqual(response.status_code, 302)


class OrdersDashboardTest(BackofficeViewTestBase):
    def test_dashboard_shows_order_and_ticket_navigation(self):
        response = self.client.get(reverse("orders:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Order control room")
        self.assertContains(response, "Order register")
        self.assertContains(response, "Kitchen &amp; Bar tickets")


class OrderDetailTest(BackofficeViewTestBase):
    def test_order_detail(self):
        order = self._create_order()
        order.add_item(self.food_item, qty=2, rate=Decimal("1500"))
        response = self.client.get(reverse("orders:order_detail", kwargs={"pk": order.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jollof Rice")

    def test_order_detail_404(self):
        response = self.client.get(reverse("orders:order_detail", kwargs={"pk": 99999}))
        self.assertEqual(response.status_code, 404)


class OrderCancelTest(BackofficeViewTestBase):
    def test_cancel_order_manager(self):
        order = self._create_order()
        response = self.client.post(
            reverse("orders:order_cancel", kwargs={"pk": order.pk}),
            {"cancel_reason": "wrong_order", "cancel_reason_note": "Test cancel"},
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "CANCELLED")

    def test_cancel_order_no_reason(self):
        order = self._create_order()
        response = self.client.post(
            reverse("orders:order_cancel", kwargs={"pk": order.pk}),
            {"cancel_reason": "", "cancel_reason_note": ""},
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "DRAFT")

    def test_cancel_order_cashier_blocked(self):
        self.client.logout()
        self.client.force_login(self.cashier_user)
        order = self._create_order()
        response = self.client.post(
            reverse("orders:order_cancel", kwargs={"pk": order.pk}),
            {"cancel_reason": "wrong_order", "cancel_reason_note": "Test"},
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "DRAFT")


class OrderReturnTest(BackofficeViewTestBase):
    def _settle_order(self, order):
        order.add_item(self.food_item, qty=2, rate=Decimal("1500"))
        order.settle([{"mode_of_payment": self.cash.pk, "amount": "3000"}])
        order.refresh_from_db()

    def test_return_creates_draft_for_manager(self):
        order = self._create_order()
        self._settle_order(order)
        response = self.client.post(reverse("orders:order_return", kwargs={"pk": order.pk}))
        self.assertEqual(response.status_code, 302)
        return_order = Order.objects.filter(is_return=True).first()
        self.assertIsNotNone(return_order)
        self.assertEqual(return_order.status, "DRAFT")
        self.assertEqual(return_order.return_against, order)

    def test_cashier_cannot_return(self):
        self.client.logout()
        self.client.force_login(self.cashier_user)
        order = self._create_order()
        self._settle_order(order)
        response = self.client.post(reverse("orders:order_return", kwargs={"pk": order.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Order.objects.filter(is_return=True).exists())

    def test_return_requires_login(self):
        self.client.logout()
        order = self._create_order()
        self._settle_order(order)
        response = self.client.post(reverse("orders:order_return", kwargs={"pk": order.pk}))
        self.assertEqual(response.status_code, 302)


class KOTListTest(BackofficeViewTestBase):
    def test_kot_list(self):
        response = self.client.get(reverse("orders:kot_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kitchen &amp; Bar Tickets")

    def test_kot_list_with_data(self):
        order = self._create_order()
        order.add_item(self.food_item, qty=1, rate=Decimal("1500"))
        order.create_tickets()
        response = self.client.get(reverse("orders:kot_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "KOT-")

    def test_kot_list_type_filter(self):
        response = self.client.get(reverse("orders:kot_list"), {"type": "New Order"})
        self.assertEqual(response.status_code, 200)


class KOTDetailTest(BackofficeViewTestBase):
    def test_kot_detail(self):
        order = self._create_order()
        order.add_item(self.food_item, qty=2, rate=Decimal("1500"))
        order.create_tickets()
        kot = order.kots.first()
        response = self.client.get(reverse("orders:kot_detail", kwargs={"pk": kot.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, kot.kot_number)

    def test_kot_detail_404(self):
        response = self.client.get(reverse("orders:kot_detail", kwargs={"pk": 99999}))
        self.assertEqual(response.status_code, 404)

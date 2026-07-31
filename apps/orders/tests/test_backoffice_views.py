from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.inventory.models import UOM, Item, ItemGroup, Warehouse
from apps.menu.models import Menu, MenuItem
from apps.orders.models import Order
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import ProductionUnit, Restaurant

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
        cls.cash = ModeOfPayment.objects.get(name="Cash")
        PaymentGLMapping.objects.create(mode_of_payment=cls.cash, default_account="Cash Account")
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.save()
        ProductionUnit.objects.create(name="Kitchen", warehouse=cls.warehouse, department="FOOD")
        cls.manager = CustomUser.objects.create_user(
            username="manager", password="testpass123", is_staff=True, is_superuser=True
        )
        cls.cashier_user = CustomUser.objects.create_user(username="cashier2", password="testpass123")

    def setUp(self):
        self.client.force_login(self.manager)

    def _create_order(self, **kwargs):
        defaults = {}
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
        response = self.client.post(reverse("orders:order_cancel", kwargs={"pk": order.pk}), {"reason": "Test cancel"})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "CANCELLED")

    def test_cancel_order_no_reason(self):
        order = self._create_order()
        response = self.client.post(reverse("orders:order_cancel", kwargs={"pk": order.pk}), {"reason": ""})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "DRAFT")

    def test_cancel_order_cashier_blocked(self):
        self.client.logout()
        self.client.force_login(self.cashier_user)
        order = self._create_order()
        response = self.client.post(reverse("orders:order_cancel", kwargs={"pk": order.pk}), {"reason": "Test"})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "DRAFT")


class KOTListTest(BackofficeViewTestBase):
    def test_kot_list(self):
        response = self.client.get(reverse("orders:kot_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kitchen Tickets")

    def test_kot_list_with_data(self):
        order = self._create_order()
        order.add_item(self.food_item, qty=1, rate=Decimal("1500"))
        order.generate_kots([])
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
        order.generate_kots([])
        kot = order.kots.first()
        response = self.client.get(reverse("orders:kot_detail", kwargs={"pk": kot.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, kot.kot_number)

    def test_kot_detail_404(self):
        response = self.client.get(reverse("orders:kot_detail", kwargs={"pk": 99999}))
        self.assertEqual(response.status_code, 404)

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.inventory.models import UOM, Item, ItemGroup, Warehouse
from apps.menu.models import Menu, MenuItem
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import ProductionUnit, Restaurant
from apps.staff.models import OpeningPayment, POSOpeningEntry

from ..models import Order

CustomUser = get_user_model()


class POSViewTestBase(TestCase):
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
        cls.menu_item = MenuItem.objects.create(menu=cls.menu, item=cls.food_item, rate=Decimal("1500"))
        cls.cash = ModeOfPayment.objects.get(name="Cash")
        PaymentGLMapping.objects.create(mode_of_payment=cls.cash, default_account="Cash Account")
        cls.cash.is_default = True
        cls.cash.save(update_fields=["is_default"])
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.default_warehouse = cls.warehouse
        cls.restaurant.save()
        ProductionUnit.objects.create(name="Kitchen", warehouse=cls.warehouse, department="FOOD")
        cls.user = CustomUser.objects.create_user(username="cashier", password="testpass123")
        cashier_group = Group.objects.get(name="RestPOS Cashier")
        cls.user.groups.add(cashier_group)

    def setUp(self):
        self.client.force_login(self.user)

    def _open_shift(self):
        entry = POSOpeningEntry.objects.create(cashier=self.user, status=POSOpeningEntry.SUBMITTED)
        OpeningPayment.objects.create(opening_entry=entry, mode_of_payment=self.cash, opening_amount=Decimal("50000"))
        return entry


class POSHomeTest(POSViewTestBase):
    def test_pos_home_no_shift(self):
        response = self.client.get(reverse("pos:pos_home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No Open Shift")

    def test_pos_home_with_shift_shows_start(self):
        self._open_shift()
        response = self.client.get(reverse("pos:pos_home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New Order")
        self.assertContains(response, "Start Order")

    def test_pos_home_login_required(self):
        self.client.logout()
        response = self.client.get(reverse("pos:pos_home"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue("/accounts/login" in response.url or "/login" in response.url)


class POSOrderStartTest(POSViewTestBase):
    def test_order_start_requires_shift(self):
        response = self.client.post(reverse("pos:pos_order_start"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 0)

    def test_order_start_creates_order(self):
        self._open_shift()
        response = self.client.post(reverse("pos:pos_order_start"), {"order_type": "DINE_IN", "guest_count": "2"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertEqual(order.order_type, "DINE_IN")
        self.assertEqual(order.guest_count, 2)
        self.assertIsNotNone(order.order_number)

    def test_order_start_takeaway(self):
        self._open_shift()
        response = self.client.post(reverse("pos:pos_order_start"), {"order_type": "TAKE_AWAY", "guest_count": "1"})
        self.assertEqual(response.status_code, 302)
        order = Order.objects.first()
        self.assertEqual(order.order_type, "TAKE_AWAY")


class POSAddItemTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_start"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.order = Order.objects.first()

    def test_add_item_htmx(self):
        response = self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}),
            {"item_id": self.food_item.pk, "qty": "2"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.items.count(), 1)
        self.assertEqual(self.order.items.first().qty, Decimal("2"))

    def test_add_item_rate_from_menu(self):
        self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}), {"item_id": self.food_item.pk, "qty": "1"}
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.items.first().rate, Decimal("1500"))

    def test_add_invalid_item_ignored(self):
        response = self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}), {"item_id": "99999", "qty": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.order.items.count(), 0)


class POSSyncTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_start"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.order = Order.objects.first()
        self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}), {"item_id": self.food_item.pk, "qty": "2"}
        )

    def test_sync_generates_kot(self):
        response = self.client.post(reverse("pos:pos_order_sync", kwargs={"pk": self.order.pk}), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.kots.count(), 1)
        self.assertEqual(self.order.kots.first().type, "New Order")

    def test_sync_marks_table_occupied(self):
        self.client.post(reverse("pos:pos_order_sync", kwargs={"pk": self.order.pk}))


class POSSettleTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_start"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.order = Order.objects.first()
        self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}), {"item_id": self.food_item.pk, "qty": "2"}
        )

    def test_settle_dine_in_blocked_without_print(self):
        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}), {f"payment_{self.cash.pk}": "3000"}
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "DRAFT")

    def test_settle_after_print(self):
        self.order.invoice_printed = True
        self.order.save(update_fields=["invoice_printed"])
        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}), {f"payment_{self.cash.pk}": "3000"}
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "SUBMITTED")
        self.assertTrue(self.order.is_paid)

    def test_settle_takeaway_no_print_needed(self):
        order = Order.objects.create(order_type="TAKE_AWAY")
        order.add_item(self.food_item, qty=1, rate=Decimal("1500"))
        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": order.pk}), {f"payment_{self.cash.pk}": "1500"}
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "SUBMITTED")

    def test_settle_no_payment_amount_rejected(self):
        self.order.invoice_printed = True
        self.order.save(update_fields=["invoice_printed"])
        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}), {f"payment_{self.cash.pk}": "0"}
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "DRAFT")


class POSCancelTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_start"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.order = Order.objects.first()

    def test_cancel_order(self):
        response = self.client.post(
            reverse("pos:pos_order_cancel", kwargs={"pk": self.order.pk}), {"reason": "Wrong table"}
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "CANCELLED")
        self.assertEqual(self.order.cancel_reason, "Wrong table")

    def test_cancel_no_reason_rejected(self):
        response = self.client.post(reverse("pos:pos_order_cancel", kwargs={"pk": self.order.pk}), {"reason": ""})
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "DRAFT")


class POSPrintTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_start"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.order = Order.objects.first()

    def test_print_marks_invoice_printed(self):
        response = self.client.post(
            reverse("pos:pos_order_print", kwargs={"pk": self.order.pk}), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.invoice_printed)

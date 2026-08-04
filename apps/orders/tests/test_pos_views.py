from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.inventory.models import UOM, Bin, Item, ItemGroup, Warehouse
from apps.menu.models import ItemAddOn, Menu, MenuItem
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import ProductionUnit, Restaurant
from apps.staff.models import OpeningPayment, POSOpeningEntry

from ..models import DINE_IN, SUBMITTED, TAKE_AWAY, Order
from ..printing import PrintResult

CustomUser = get_user_model()


class POSViewTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(company="Test Co")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group_food = ItemGroup.objects.create(name="Food")
        cls.group_drinks = ItemGroup.objects.create(name="Drinks")
        cls.warehouse = Warehouse.objects.create(name="Kitchen")
        cls.food_item = Item.objects.create(
            item_name="Jollof Rice", item_group=cls.group_food, stock_uom=cls.uom, department="FOOD", is_sales_item=True
        )
        cls.menu = Menu.objects.create(name="Main Menu")
        cls.menu_item = MenuItem.objects.create(menu=cls.menu, item=cls.food_item, rate=Decimal("1500"))
        cls.drink_item = Item.objects.create(
            item_name="Coke",
            item_group=cls.group_drinks,
            stock_uom=cls.uom,
            department="DRINKS",
            is_sales_item=True,
            is_stock_item=True,
        )
        cls.drink_menu_item = MenuItem.objects.create(menu=cls.menu, item=cls.drink_item, rate=Decimal("500"))
        Bin.objects.create(item=cls.food_item, warehouse=cls.warehouse, actual_qty=Decimal("100"))
        Bin.objects.create(item=cls.drink_item, warehouse=cls.warehouse, actual_qty=Decimal("2"))
        cls.cash, _ = ModeOfPayment.objects.get_or_create(name="Cash", defaults={"type": "CASH"})
        PaymentGLMapping.objects.get_or_create(mode_of_payment=cls.cash, defaults={"default_account": "Cash Account"})
        cls.cash.is_default = True
        cls.cash.save(update_fields=["is_default"])
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.default_warehouse = cls.warehouse
        cls.restaurant.save()
        ProductionUnit.objects.create(name="Kitchen", warehouse=cls.warehouse, department="FOOD")
        ProductionUnit.objects.create(name="Bar", warehouse=cls.warehouse, department="DRINKS")
        cls.user = CustomUser.objects.create_user(username="cashier", password="testpass123")
        cashier_group = Group.objects.get(name="RestPOS Cashier")
        cls.user.groups.add(cashier_group)

    def setUp(self):
        self.client.force_login(self.user)

    def _open_shift(self):
        entry = POSOpeningEntry.objects.create(cashier=self.user)
        OpeningPayment.objects.create(opening_entry=entry, mode_of_payment=self.cash, opening_amount=Decimal("50000"))
        entry.submit()
        return entry


class POSHomeTest(POSViewTestBase):
    def test_pos_home_no_shift(self):
        response = self.client.get(reverse("pos:pos_home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No Open Shift")

    def test_pos_home_with_shift_shows_drafts(self):
        self._open_shift()
        response = self.client.get(reverse("pos:pos_home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Opened at")
        self.assertContains(response, "No open orders")

    def test_pos_home_login_required(self):
        self.client.logout()
        response = self.client.get(reverse("pos:pos_home"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue("/accounts/login" in response.url or "/login" in response.url)

    def test_draft_cap_blocks_new_order(self):
        self.restaurant.max_open_drafts = 1
        self.restaurant.save(update_fields=["max_open_drafts"])
        self._open_shift()
        first = self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.assertEqual(first.status_code, 302)
        second = self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Order.objects.filter(status="DRAFT").count(), 1)


class POSOrderStartTest(POSViewTestBase):
    def test_order_start_requires_shift(self):
        response = self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 0)

    def test_order_start_creates_order(self):
        self._open_shift()
        response = self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "2"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertEqual(order.order_type, "DINE_IN")
        self.assertEqual(order.guest_count, 2)
        self.assertIsNotNone(order.order_number)

    def test_order_start_takeaway(self):
        self._open_shift()
        response = self.client.post(reverse("pos:pos_order_new"), {"order_type": "TAKE_AWAY", "guest_count": "1"})
        self.assertEqual(response.status_code, 302)
        order = Order.objects.first()
        self.assertEqual(order.order_type, "TAKE_AWAY")

    def test_order_start_defaults_to_dine_in(self):
        self._open_shift()
        response = self.client.post(reverse("pos:pos_order_new"), {"guest_count": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.get().order_type, DINE_IN)


class POSAddItemTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
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

    def test_add_and_update_drink_respects_available_limit(self):
        add_url = reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk})
        self.client.post(add_url, {"item_id": self.drink_item.pk, "qty": "2"})
        line = self.order.items.get(item=self.drink_item)
        response = self.client.post(
            reverse("pos:pos_order_update_item", kwargs={"pk": self.order.pk, "item_pk": line.pk}),
            {"action": "increment"},
            HTTP_HX_REQUEST="true",
        )
        line.refresh_from_db()
        self.assertEqual(line.qty, Decimal("2"))
        self.assertContains(response, "Insufficient stock")
        self.assertEqual(Bin.objects.get(item=self.drink_item, warehouse=self.warehouse).reserved_qty, Decimal("2"))

    def test_catalog_disables_out_of_stock_drink_without_htmx_action(self):
        Bin.objects.filter(item=self.drink_item, warehouse=self.warehouse).update(actual_qty=Decimal("0"))
        response = self.client.get(reverse("pos:pos_order_screen", kwargs={"pk": self.order.pk}))
        self.assertContains(response, "Out of stock")
        self.assertContains(response, f'aria-label="{self.drink_item.item_name}: Out of stock"')
        self.assertNotContains(
            response,
            f'hx-vals=\'{{"item_id":"{self.drink_item.pk}","qty":"1"}}\'',
        )

    def test_catalog_disables_invalid_non_stock_drink_configuration(self):
        self.drink_item.is_stock_item = False
        self.drink_item.save(update_fields=["is_stock_item"])
        response = self.client.get(reverse("pos:pos_order_screen", kwargs={"pk": self.order.pk}))
        self.assertContains(response, "Setup required: mark this drink as a stock item")
        add_response = self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}),
            {"item_id": self.drink_item.pk, "qty": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(add_response, "not configured as a stock item")
        self.assertFalse(self.order.items.filter(item=self.drink_item).exists())

    def test_catalog_treats_disabled_bar_warehouse_as_unconfigured(self):
        Warehouse.objects.filter(pk=self.warehouse.pk).update(disabled=True)
        response = self.client.get(reverse("pos:pos_order_screen", kwargs={"pk": self.order.pk}))
        self.assertContains(response, "Setup required: configure the Bar/POS warehouse")
        self.assertContains(response, f'aria-label="{self.drink_item.item_name}: Setup required')

    def test_add_on_dialog_adds_parent_and_selected_add_on_to_active_customer(self):
        add_on_item = Item.objects.create(
            item_name="Extra Sauce",
            item_group=self.group_food,
            stock_uom=self.uom,
            department="FOOD",
            is_sales_item=True,
        )
        add_on_menu_item = MenuItem.objects.create(menu=self.menu, item=add_on_item, rate=Decimal("300"))
        ItemAddOn.objects.create(parent_item=self.food_item, add_on_item=add_on_item)

        response = self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}),
            {
                "item_id": self.food_item.pk,
                "qty": "2",
                "add_on_ids": [str(add_on_item.pk)],
                "comments": "No pepper",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        lines = list(self.order.items.order_by("item_id"))
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].customer_index, 1)
        self.assertEqual(lines[1].customer_index, 1)
        self.assertEqual(lines[0].qty, Decimal("2"))
        self.assertEqual(lines[0].comments, "No pepper")
        self.assertEqual(lines[1].rate, add_on_menu_item.rate)

    def test_invalid_add_on_does_not_add_parent_item(self):
        unrelated = Item.objects.create(
            item_name="Unrelated",
            item_group=self.group_food,
            stock_uom=self.uom,
            department="FOOD",
            is_sales_item=True,
        )
        response = self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}),
            {"item_id": self.food_item.pk, "qty": "1", "add_on_ids": [str(unrelated.pk)]},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not available for this item")
        self.assertEqual(self.order.items.count(), 0)


class POSSyncTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
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
        self.assertEqual(self.order.kots.first().print_status, "PRINTED")
        self.assertEqual(self.order.kots.first().created_by, self.user)

    def test_sync_locks_item_changes(self):
        self.client.post(reverse("pos:pos_order_sync", kwargs={"pk": self.order.pk}))
        response = self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}),
            {"item_id": self.food_item.pk, "qty": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "Cancel it before making changes")
        self.assertEqual(self.order.items.count(), 1)

    def test_reprint_does_not_create_another_ticket(self):
        self.user.groups.add(Group.objects.get(name="RestPOS Manager"))
        self.client.post(reverse("pos:pos_order_sync", kwargs={"pk": self.order.pk}))
        ticket_count = self.order.kots.count()
        response = self.client.post(
            reverse(
                "pos:pos_order_ticket_print",
                kwargs={"pk": self.order.pk, "ticket_type": "kitchen", "action": "reprint"},
            ),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(self.order.kots.count(), ticket_count)
        self.assertContains(response, "Kitchen ticket reprinted")

    @patch("apps.orders.views_pos.printing.print_ticket")
    def test_failed_reprint_returns_retry_state(self, print_ticket):
        self.user.groups.add(Group.objects.get(name="RestPOS Manager"))
        self.client.post(reverse("pos:pos_order_sync", kwargs={"pk": self.order.pk}))
        print_ticket.return_value = PrintResult(success=False, ticket_type="kitchen")
        response = self.client.post(
            reverse(
                "pos:pos_order_ticket_print",
                kwargs={"pk": self.order.pk, "ticket_type": "kitchen", "action": "reprint"},
            ),
            HTTP_HX_REQUEST="true",
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.kots.first().print_status, "PENDING")
        self.assertContains(response, "Retry Kitchen Printing")

    def test_sync_marks_table_occupied(self):
        self.client.post(reverse("pos:pos_order_sync", kwargs={"pk": self.order.pk}))


class POSSettleTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.order = Order.objects.first()
        self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}), {"item_id": self.food_item.pk, "qty": "2"}
        )

    def test_settle_dine_in_without_print(self):
        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}), {f"payment_{self.cash.pk}": "3000"}
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "SUBMITTED")
        self.assertFalse(self.order.invoice_printed)

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
        order = Order.objects.create(
            order_type="TAKE_AWAY",
            opening_entry=POSOpeningEntry.objects.filter(status=POSOpeningEntry.SUBMITTED).first(),
        )
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
        self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.order = Order.objects.first()
        self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}),
            {"item_id": self.food_item.pk, "qty": "1"},
        )
        self.client.post(reverse("pos:pos_order_sync", kwargs={"pk": self.order.pk}))

    def test_cancel_order(self):
        response = self.client.post(
            reverse("pos:pos_order_cancel", kwargs={"pk": self.order.pk}),
            {"cancel_reason": "wrong_order", "cancel_reason_note": "Wrong table"},
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "CANCELLED")
        self.assertEqual(self.order.cancel_reason, "wrong_order")
        self.assertEqual(self.order.cancel_reason_note, "Wrong table")
        self.assertEqual(self.order.cancelled_by, self.user)
        self.assertIsNotNone(self.order.cancelled_at)
        original = self.order.kots.get(type="New Order")
        cancellation = self.order.kots.get(type="Cancelled")
        self.assertEqual(original.status, "CANCELLED")
        self.assertEqual(original.print_status, "PRINTED")
        self.assertEqual(cancellation.production_unit_id, original.production_unit_id)
        self.assertEqual(cancellation.print_status, "PRINTED")

    def test_cancel_no_reason_rejected(self):
        response = self.client.post(
            reverse("pos:pos_order_cancel", kwargs={"pk": self.order.pk}),
            {"cancel_reason": "", "cancel_reason_note": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "DRAFT")


class POSPrintTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.order = Order.objects.first()
        self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}),
            {"item_id": self.food_item.pk, "qty": "1"},
        )

    @patch("apps.orders.views_pos.printing.print_receipt")
    def test_print_marks_invoice_printed(self, print_receipt):
        print_receipt.return_value = PrintResult(success=True, ticket_type="receipt")
        response = self.client.post(
            reverse("pos:pos_order_print", kwargs={"pk": self.order.pk}), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        print_receipt.assert_called_once_with(self.order)
        self.order.refresh_from_db()
        self.assertTrue(self.order.invoice_printed)
        self.assertContains(response, "Receipt printed successfully.")
        self.assertContains(response, "Reprint Receipt")

    @patch("apps.orders.views_pos.printing.print_receipt")
    def test_print_freezes_item_changes(self, print_receipt):
        print_receipt.return_value = PrintResult(success=True, ticket_type="receipt")
        self.client.post(reverse("pos:pos_order_print", kwargs={"pk": self.order.pk}), HTTP_HX_REQUEST="true")
        response = self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}),
            {"item_id": self.food_item.pk, "qty": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "receipt has been printed")
        self.assertEqual(self.order.items.count(), 1)

    @patch("apps.orders.views_pos.printing.print_receipt")
    def test_reprint_receipt_for_current_draft(self, print_receipt):
        print_receipt.return_value = PrintResult(success=True, ticket_type="receipt")
        self.order.invoice_printed = True
        self.order.save(update_fields=["invoice_printed"])
        response = self.client.post(
            reverse("pos:pos_order_print", kwargs={"pk": self.order.pk}), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.order.invoice_printed)
        self.assertContains(response, "Receipt reprinted successfully.")
        self.assertContains(response, "Reprint Receipt")

    @patch("apps.orders.views_pos.printing.print_receipt")
    def test_failed_receipt_print_does_not_mark_invoice_printed(self, print_receipt):
        print_receipt.return_value = PrintResult(success=False, ticket_type="receipt")
        response = self.client.post(
            reverse("pos:pos_order_print", kwargs={"pk": self.order.pk}), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertFalse(self.order.invoice_printed)
        self.assertContains(response, "Receipt printing failed. Try again.")

    @patch("apps.orders.views_pos.printing.print_receipt")
    def test_failed_receipt_reprint_preserves_printed_state(self, print_receipt):
        print_receipt.return_value = PrintResult(success=False, ticket_type="receipt")
        self.order.invoice_printed = True
        self.order.save(update_fields=["invoice_printed"])
        response = self.client.post(
            reverse("pos:pos_order_print", kwargs={"pk": self.order.pk}), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.invoice_printed)
        self.assertContains(response, "Receipt reprint failed. Try again.")

    @patch("apps.orders.views_pos.printing.print_receipt")
    def test_takeaway_can_print_receipt(self, print_receipt):
        print_receipt.return_value = PrintResult(success=True, ticket_type="receipt")
        self.order.order_type = TAKE_AWAY
        self.order.save(update_fields=["order_type"])
        response = self.client.post(
            reverse("pos:pos_order_print", kwargs={"pk": self.order.pk}), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.invoice_printed)
        self.assertContains(response, "Receipt printed successfully.")


class POSClearTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.order = Order.objects.first()
        self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}), {"item_id": self.food_item.pk, "qty": "2"}
        )

    def test_clear_is_blocked_after_receipt_print(self):
        self.order.invoice_printed = True
        self.order.save(update_fields=["invoice_printed"])
        response = self.client.post(
            reverse("pos:pos_order_clear", kwargs={"pk": self.order.pk}), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.items.count(), 1)
        self.assertEqual(self.order.status, "DRAFT")
        self.assertEqual(self.order.grand_total, Decimal("3000.00"))
        self.assertTrue(self.order.invoice_printed)

    def test_clear_unsynced_items_no_kot(self):
        self.client.post(reverse("pos:pos_order_clear", kwargs={"pk": self.order.pk}))
        self.order.refresh_from_db()
        self.assertEqual(self.order.kots.count(), 0)

    def test_clear_sent_order_is_blocked(self):
        self.client.post(reverse("pos:pos_order_sync", kwargs={"pk": self.order.pk}))
        self.assertEqual(self.order.kots.count(), 1)
        response = self.client.post(
            reverse("pos:pos_order_clear", kwargs={"pk": self.order.pk}), HTTP_HX_REQUEST="true"
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.items.count(), 1)
        self.assertContains(response, "Use Cancel Order instead of Clear")

    def test_clear_requires_draft(self):
        Order.objects.filter(pk=self.order.pk).update(status=SUBMITTED)
        response = self.client.post(reverse("pos:pos_order_clear", kwargs={"pk": self.order.pk}))
        self.assertEqual(response.status_code, 404)

    def test_clear_releases_drink_reservation(self):
        self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}),
            {"item_id": self.drink_item.pk, "qty": "2"},
        )
        self.client.post(reverse("pos:pos_order_clear", kwargs={"pk": self.order.pk}))
        self.assertEqual(Bin.objects.get(item=self.drink_item, warehouse=self.warehouse).reserved_qty, Decimal("0"))


class POSSplitViewTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.order = Order.objects.first()
        self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}), {"item_id": self.food_item.pk, "qty": "1"}
        )
        self._meta_url = reverse("pos:pos_order_update_meta", kwargs={"pk": self.order.pk})

    def _set_guest_count(self, n):
        return self.client.post(self._meta_url, {"guest_count": str(n)}, HTTP_HX_REQUEST="true")

    def _add_to_card(self, card_idx):
        self.client.post(reverse("pos:pos_customer_card_activate", kwargs={"pk": self.order.pk, "idx": card_idx}))
        return self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}), {"item_id": self.food_item.pk, "qty": "1"}
        )

    def test_raise_guest_count_groups_items(self):
        response = self._set_guest_count(2)
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.guest_count, 2)
        self.assertContains(response, "Customer 1")
        self.assertContains(response, "Customer 2")
        self.assertContains(response, "subtotal")

    def test_delta_raise_guest_count(self):
        response = self.client.post(self._meta_url, {"guest_delta": "1"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.guest_count, 2)

    def test_lower_blocked_when_guest_has_items(self):
        self._set_guest_count(2)
        self._add_to_card(2)
        response = self._set_guest_count(1)
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.guest_count, 2)
        self.assertContains(response, "Remove Customer 2")

    def test_lower_allowed_when_higher_guest_empty(self):
        self._set_guest_count(2)
        response = self._set_guest_count(1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.guest_count, 1)
        self.assertNotContains(response, "Customer 2")

    def test_delta_lower_blocked_with_items(self):
        self._set_guest_count(2)
        self._add_to_card(2)
        response = self.client.post(self._meta_url, {"guest_delta": "-1"}, HTTP_HX_REQUEST="true")
        self.order.refresh_from_db()
        self.assertEqual(self.order.guest_count, 2)
        self.assertContains(response, "Remove Customer 2")

    def test_guest_subtotal_renders(self):
        self._set_guest_count(2)
        self._add_to_card(2)
        response = self.client.get(reverse("pos:pos_order_screen", kwargs={"pk": self.order.pk}))
        self.assertContains(response, "Customer 1 subtotal")
        self.assertContains(response, "Customer 2 subtotal")

    def test_active_card_switch_assigns_items(self):
        self._set_guest_count(2)
        self._add_to_card(2)
        self.order.refresh_from_db()
        self.assertEqual(self.order.items.filter(customer_index=2).count(), 1)
        self.assertEqual(self.order.items.filter(customer_index=1).count(), 1)

    def test_change_guest_count_guard_direct(self):
        self._set_guest_count(2)
        self._add_to_card(2)
        with self.assertRaises(ValidationError):
            self.order.change_guest_count(1)

    def test_order_type_update_renders_selected_state(self):
        response = self.client.post(
            self._meta_url,
            {"order_type": TAKE_AWAY},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.order_type, TAKE_AWAY)
        self.assertContains(response, 'aria-pressed="true"')
        self.assertContains(response, "Take Away")

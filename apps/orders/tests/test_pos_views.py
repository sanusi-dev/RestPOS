import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.inventory.models import UOM, Bin, Item, ItemGroup, Warehouse
from apps.menu.models import ItemAddOn, Menu, MenuItem
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import ProductionUnit, Restaurant
from apps.staff.models import OpeningPayment, POSClosingEntry, POSOpeningEntry

from ..models import CANCEL_REASON_WRONG_ORDER, CANCELLED, DINE_IN, SUBMITTED, TAKE_AWAY, Order
from ..printing import PrintResult
from ..services import add_order_line, create_tickets, settle_order

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
        self.assertContains(response, "No open shift")
        self.assertContains(response, 'id="pos-main"')

    def test_pos_home_htmx_returns_only_the_draft_surface(self):
        self._open_shift()

        response = self.client.get(reverse("pos:pos_home"), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No open orders")
        self.assertNotContains(response, "<html")
        self.assertNotContains(response, 'id="pos-main"')
        self.assertContains(response, 'id="pos-header-nav"')
        self.assertContains(response, 'hx-swap-oob="outerHTML"')

    def test_no_shift_surface_marks_open_shift_form_for_htmx(self):
        response = self.client.get(reverse("pos:pos_home"), HTTP_HX_REQUEST="true")

        self.assertContains(response, f'hx-post="{reverse("pos:pos_open_shift")}"')
        self.assertContains(response, 'hx-target="#pos-main"')

    def test_pos_home_with_shift_shows_drafts(self):
        self._open_shift()
        response = self.client.get(reverse("pos:pos_home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No open orders")

    def test_pos_home_renders_draft_docket_context(self):
        opening = self._open_shift()
        order = Order.objects.create(opening_entry=opening, order_type=TAKE_AWAY, guest_count=2)
        order.assign_order_number()
        add_order_line(order, self.food_item, qty=2, rate=Decimal("1500"))

        response = self.client.get(reverse("pos:pos_home"))

        self.assertEqual(response.context["draft_count"], 1)
        self.assertEqual(response.context["max_open_drafts"], self.restaurant.max_open_drafts)
        self.assertFalse(response.context["draft_cap_reached"])
        self.assertContains(response, f"#{order.order_number}")
        self.assertContains(response, "Take Away")
        self.assertContains(response, "2 customers")
        self.assertContains(response, self.food_item.item_name)
        self.assertContains(response, "Resume order")
        self.assertContains(response, "Draft")

    def test_pos_home_shows_sent_and_receipt_printed_states(self):
        opening = self._open_shift()
        sent_order = Order.objects.create(opening_entry=opening)
        sent_order.assign_order_number()
        add_order_line(sent_order, self.food_item, qty=1, rate=Decimal("1500"))
        create_tickets(sent_order, created_by=self.user)
        printed_order = Order.objects.create(opening_entry=opening, invoice_printed=True)
        printed_order.assign_order_number()

        response = self.client.get(reverse("pos:pos_home"))

        self.assertContains(response, "Sent")
        self.assertContains(response, "Receipt printed")

    def test_pos_home_filters_draft_and_sent_orders(self):
        opening = self._open_shift()
        draft_order = Order.objects.create(opening_entry=opening, order_number=201)
        add_order_line(draft_order, self.food_item, qty=1, rate=Decimal("1500"))
        sent_order = Order.objects.create(opening_entry=opening, order_number=202)
        add_order_line(sent_order, self.food_item, qty=1, rate=Decimal("1500"))
        create_tickets(sent_order, created_by=self.user)

        draft_response = self.client.get(reverse("pos:pos_home"), {"filter": "draft"})
        sent_response = self.client.get(reverse("pos:pos_home"), {"filter": "sent"})

        self.assertContains(draft_response, "#201")
        self.assertNotContains(draft_response, "#202")
        self.assertContains(sent_response, "#202")
        self.assertNotContains(sent_response, "#201")
        self.assertEqual(draft_response.context["draft_count"], 2)

    def test_pos_home_searches_order_number_and_item_name(self):
        opening = self._open_shift()
        order = Order.objects.create(opening_entry=opening, order_number=301)
        add_order_line(order, self.food_item, qty=1, rate=Decimal("1500"))

        number_response = self.client.get(reverse("pos:pos_home"), {"q": "301"})
        item_response = self.client.get(reverse("pos:pos_home"), {"q": self.food_item.item_name})
        missing_response = self.client.get(reverse("pos:pos_home"), {"q": "does-not-exist"})

        self.assertContains(number_response, "#301")
        self.assertContains(item_response, "#301")
        self.assertNotContains(missing_response, "#301")

    def test_pos_home_disables_new_order_at_draft_cap(self):
        self.restaurant.max_open_drafts = 1
        self.restaurant.save(update_fields=["max_open_drafts"])
        opening = self._open_shift()
        Order.objects.create(opening_entry=opening)

        response = self.client.get(reverse("pos:pos_home"))

        self.assertTrue(response.context["draft_cap_reached"])
        self.assertContains(response, "disabled")

    def test_pos_home_login_required(self):
        self.client.logout()
        response = self.client.get(reverse("pos:pos_home"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue("/accounts/login" in response.url or "/login" in response.url)

    def test_open_shift_saves_notes(self):
        response = self.client.post(
            reverse("pos:pos_open_shift"),
            {f"mop_{self.cash.pk}": "5000", "remarks": "Opening float checked"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(POSOpeningEntry.objects.get().remarks, "Opening float checked")

    def test_open_shift_htmx_renders_draft_orders_and_pushes_home_url(self):
        response = self.client.post(
            reverse("pos:pos_open_shift"),
            {f"mop_{self.cash.pk}": "5000"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Push-Url"], reverse("pos:pos_home"))
        self.assertContains(response, "No open orders")
        self.assertNotContains(response, 'id="pos-main"')

    def test_draft_cap_blocks_new_order(self):
        self.restaurant.max_open_drafts = 1
        self.restaurant.save(update_fields=["max_open_drafts"])
        self._open_shift()
        first = self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.assertEqual(first.status_code, 302)
        second = self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Order.objects.filter(status="DRAFT").count(), 1)


class POSShiftCloseTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self.opening = self._open_shift()

    def test_close_shift_page_shows_reconciliation_fields(self):
        response = self.client.get(reverse("pos:pos_close_shift"))

        self.assertContains(response, "Expected")
        self.assertContains(response, "Counted")
        self.assertContains(response, "Variance")
        self.assertContains(response, "Close shift")
        self.assertNotContains(response, "Notes")

    def test_close_shift_htmx_get_returns_only_the_close_surface(self):
        response = self.client.get(reverse("pos:pos_close_shift"), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Count the drawer")
        self.assertNotContains(response, "<html")
        self.assertNotContains(response, 'id="pos-main"')
        self.assertContains(response, f'hx-post="{reverse("pos:pos_close_shift")}"')
        self.assertContains(response, 'hx-swap-oob="outerHTML"')

    def test_close_shift_is_blocked_by_open_order(self):
        Order.objects.create(opening_entry=self.opening)

        response = self.client.get(reverse("pos:pos_close_shift"))

        self.assertContains(response, "Finish open orders first")
        self.assertContains(response, "1 open order")
        self.opening.refresh_from_db()
        self.assertIsNone(self.opening.closing_entry_id)

    def test_close_shift_post_rechecks_open_orders(self):
        Order.objects.create(opening_entry=self.opening)

        response = self.client.post(reverse("pos:pos_close_shift"), {})

        self.assertRedirects(response, reverse("pos:pos_home"))
        self.opening.refresh_from_db()
        self.assertIsNone(self.opening.closing_entry_id)

    def test_close_shift_saves_notes_and_closes_opening(self):
        response = self.client.get(reverse("pos:pos_close_shift"))
        form_data = response.context["form_data"]
        post_data = {form["closing_amount"].html_name: str(payment.expected_amount) for payment, form in form_data}
        post_data["remarks"] = "Counted with manager"

        response = self.client.post(reverse("pos:pos_close_shift"), post_data)

        self.assertEqual(response.status_code, 302)
        self.opening.refresh_from_db()
        closing = POSClosingEntry.objects.get(opening_entry=self.opening)
        self.assertEqual(closing.remarks, "Counted with manager")
        self.assertEqual(closing.status, closing.SUBMITTED)
        self.assertEqual(self.opening.closing_entry_id, closing.pk)

    def test_close_shift_get_does_not_create_closing_rows(self):
        from apps.staff.models import ClosingPayment

        before_entries = POSClosingEntry.objects.count()
        before_payments = ClosingPayment.objects.count()
        response = self.client.get(reverse("pos:pos_close_shift"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(POSClosingEntry.objects.count(), before_entries)
        self.assertEqual(ClosingPayment.objects.count(), before_payments)

    def test_close_shift_htmx_success_returns_no_shift_surface_and_pushes_home_url(self):
        response = self.client.get(reverse("pos:pos_close_shift"))
        form_data = response.context["form_data"]
        post_data = {form["closing_amount"].html_name: str(payment.expected_amount) for payment, form in form_data}

        response = self.client.post(
            reverse("pos:pos_close_shift"),
            post_data,
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Push-Url"], reverse("pos:pos_home"))
        self.assertContains(response, "No open shift")
        self.assertNotContains(response, 'id="pos-main"')


class POSOrderHistoryTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self.opening = self._open_shift()
        self.sale = Order.objects.create(
            opening_entry=self.opening,
            status=SUBMITTED,
            is_paid=True,
            order_number=101,
            invoice_number="INV-101",
            grand_total=Decimal("1500"),
        )
        self.return_order = Order.objects.create(
            opening_entry=self.opening,
            status=SUBMITTED,
            is_paid=True,
            is_return=True,
            order_number=102,
            invoice_number="RET-102",
            grand_total=Decimal("-500"),
        )
        self.cancelled = Order.objects.create(
            opening_entry=self.opening,
            status=CANCELLED,
            cancel_reason=CANCEL_REASON_WRONG_ORDER,
            cancelled_at=timezone.now(),
            cancelled_by=self.user,
            order_number=103,
            invoice_number="CAN-103",
        )

    def test_history_defaults_to_completed_sales(self):
        response = self.client.get(reverse("pos:pos_order_history"))

        self.assertContains(response, "#101")
        self.assertNotContains(response, "#102")
        self.assertNotContains(response, "#103")
        self.assertContains(response, "Open")
        self.assertContains(response, "History")

    def test_history_htmx_returns_only_the_history_surface(self):
        response = self.client.get(reverse("pos:pos_order_history"), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{self.sale.order_number}")
        self.assertNotContains(response, "<html")
        self.assertNotContains(response, 'id="pos-main"')
        self.assertContains(response, 'hx-swap-oob="outerHTML"')
        # Cashiers without the restaurant setting only see Sales.
        self.assertNotContains(response, 'hx-get="?status=all')
        self.assertContains(response, 'hx-get="?status=sales')

    def test_history_full_filters_when_restaurant_setting_enabled(self):
        self.restaurant.pos_allow_full_history = True
        self.restaurant.save(update_fields=["pos_allow_full_history"])
        response = self.client.get(reverse("pos:pos_order_history"))
        self.assertContains(response, 'hx-get="?status=all')
        self.assertContains(response, 'hx-get="?status=returns')
        self.assertContains(response, 'hx-get="?status=cancelled')

    def test_history_view_link_targets_drawer_without_url_push(self):
        response = self.client.get(reverse("pos:pos_order_history"))

        self.assertContains(response, f'id="order-view-{self.sale.pk}"')
        self.assertContains(response, 'hx-target="#order-details-drawer"')
        self.assertContains(response, 'hx-push-url="false"')
        self.assertContains(response, 'aria-controls="order-details-drawer"')

    def test_history_detail_drawer_returns_only_drawer_fragment(self):
        response = self.client.get(
            reverse("pos:pos_order_history_detail", kwargs={"pk": self.sale.pk}),
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="order-details-drawer",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'role="dialog"')
        self.assertContains(response, 'aria-modal="true"')
        self.assertContains(response, "Kitchen status")
        self.assertNotContains(response, "Payment status")
        self.assertContains(response, "Items (0)")
        self.assertContains(response, "Discount")
        self.assertContains(response, "₦0")
        self.assertContains(response, "No items recorded")
        self.assertContains(response, "orderDetailsDrawer")
        self.assertContains(response, "animate: true")
        self.assertNotContains(response, "<html")
        self.assertNotContains(response, 'id="pos-main"')
        self.assertNotContains(response, 'hx-swap-oob="outerHTML"')
        self.assertNotIn("HX-Push-Url", response)

    def test_history_detail_print_from_drawer_does_not_push_url(self):
        with patch(
            "apps.orders.views_pos.printing.print_receipt",
            return_value=PrintResult(success=True, ticket_type="receipt"),
        ):
            response = self.client.post(
                reverse("pos:pos_order_history_print", kwargs={"pk": self.sale.pk}),
                HTTP_HX_REQUEST="true",
                HTTP_HX_TARGET="order-details-drawer",
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HX-Push-Url", response)
        self.assertContains(response, 'role="dialog"')
        self.assertContains(response, "Print receipt")
        # Re-render after print must not re-run the slide-in animation.
        self.assertContains(response, "animate: false")
        self.assertNotContains(response, "<html")

    def test_history_all_filter_includes_sales_returns_and_cancelled(self):
        self.restaurant.pos_allow_full_history = True
        self.restaurant.save(update_fields=["pos_allow_full_history"])
        response = self.client.get(reverse("pos:pos_order_history"), {"status": "all"})

        self.assertContains(response, "#101")
        self.assertContains(response, "#102")
        self.assertContains(response, "#103")

    def test_cashier_without_full_history_is_forced_to_sales(self):
        response = self.client.get(reverse("pos:pos_order_history"), {"status": "all"})
        self.assertContains(response, "#101")
        self.assertNotContains(response, "#102")
        self.assertNotContains(response, "#103")

    def test_history_with_cleared_date_shows_older_orders(self):
        older_sale = Order.objects.create(
            opening_entry=self.opening,
            status=SUBMITTED,
            is_paid=True,
            order_number=100,
            invoice_number="INV-100",
            posting_date=timezone.localdate() - timedelta(days=1),
            grand_total=Decimal("900"),
        )

        response = self.client.get(reverse("pos:pos_order_history"), {"status": "sales", "date": ""})

        self.assertContains(response, f"#{older_sale.order_number}")

    def test_history_filters_returns_and_cancelled(self):
        self.restaurant.pos_allow_full_history = True
        self.restaurant.save(update_fields=["pos_allow_full_history"])
        returns_response = self.client.get(reverse("pos:pos_order_history"), {"status": "returns"})
        cancelled_response = self.client.get(reverse("pos:pos_order_history"), {"status": "cancelled"})

        self.assertContains(returns_response, "#102")
        self.assertNotContains(returns_response, "#101")
        self.assertContains(cancelled_response, "#103")
        self.assertNotContains(cancelled_response, "#101")

    def test_history_filters_by_order_type(self):
        takeaway = Order.objects.create(
            opening_entry=self.opening,
            status=SUBMITTED,
            is_paid=True,
            order_type=TAKE_AWAY,
            order_number=104,
            invoice_number="INV-104",
        )

        response = self.client.get(
            reverse("pos:pos_order_history"),
            {"status": "sales", "order_type": TAKE_AWAY},
        )

        self.assertContains(response, f"#{takeaway.order_number}")
        self.assertNotContains(response, "#101")
        self.assertContains(response, f'name="order_type" value="{TAKE_AWAY}"')

    def test_history_detail_is_read_only_and_reprints_submitted_receipt(self):
        detail_url = reverse("pos:pos_order_history_detail", kwargs={"pk": self.sale.pk})
        response = self.client.get(detail_url)

        self.assertContains(response, f"#{self.sale.order_number}")
        self.assertContains(response, "Reprint receipt")
        with patch(
            "apps.orders.views_pos.printing.print_receipt",
            return_value=PrintResult(success=True, ticket_type="receipt"),
        ):
            response = self.client.post(reverse("pos:pos_order_history_print", kwargs={"pk": self.sale.pk}))
        self.assertRedirects(response, detail_url)

        with patch(
            "apps.orders.views_pos.printing.print_receipt",
            return_value=PrintResult(success=True, ticket_type="receipt"),
        ):
            response = self.client.post(
                reverse("pos:pos_order_history_print", kwargs={"pk": self.sale.pk}),
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Push-Url"], detail_url)
        self.assertContains(response, f"#{self.sale.order_number}")
        self.assertNotContains(response, "<html")

    def test_history_detail_htmx_returns_surface_with_history_active(self):
        response = self.client.get(
            reverse("pos:pos_order_history_detail", kwargs={"pk": self.sale.pk}),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{self.sale.order_number}")
        self.assertNotContains(response, "<html")
        self.assertNotContains(response, 'id="pos-main"')
        self.assertContains(response, 'id="pos-header-nav"')
        self.assertContains(response, 'aria-current="page"')
        self.assertNotContains(response, 'id="catalog-search"')

    def test_history_detail_groups_items_by_customer_and_shows_payments(self):
        order = Order.objects.create(opening_entry=self.opening, guest_count=2)
        add_order_line(order, self.food_item, qty=1, customer_index=1, rate=Decimal("1500"))
        add_order_line(order, self.drink_item, qty=2, customer_index=2, rate=Decimal("500"))
        settle_order(
            order, [{"mode_of_payment": self.cash.pk, "amount": "2500", "reference_no": ""}], cashier=self.user
        )

        response = self.client.get(reverse("pos:pos_order_history_detail", kwargs={"pk": order.pk}))

        self.assertContains(response, "Customer 1")
        self.assertContains(response, "Customer 2")
        self.assertContains(response, "Jollof Rice")
        self.assertContains(response, "Coke")
        self.assertContains(response, "Cash")

    def test_cancelled_history_receipt_cannot_be_reprinted(self):
        response = self.client.post(reverse("pos:pos_order_history_print", kwargs={"pk": self.cancelled.pk}))

        self.assertEqual(response.status_code, 404)


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

    def test_order_start_htmx_renders_order_surface_and_pushes_order_url(self):
        self._open_shift()

        response = self.client.post(
            reverse("pos:pos_order_new"),
            {"order_type": "DINE_IN", "guest_count": "2"},
            HTTP_HX_REQUEST="true",
        )
        order = Order.objects.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["HX-Push-Url"],
            reverse("pos:pos_order_screen", kwargs={"pk": order.pk}),
        )
        self.assertContains(response, "Jollof Rice")
        self.assertNotContains(response, "<html")
        self.assertNotContains(response, 'id="pos-main"')

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

    def test_add_on_dialog_defaults_parent_and_add_on_to_one_each(self):
        add_on_item = Item.objects.create(
            item_name="Extra Sauce",
            item_group=self.group_food,
            stock_uom=self.uom,
            department="FOOD",
            is_sales_item=True,
        )
        MenuItem.objects.create(menu=self.menu, item=add_on_item, rate=Decimal("300"))
        ItemAddOn.objects.create(parent_item=self.food_item, add_on_item=add_on_item)

        response = self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}),
            {"item_id": self.food_item.pk, "add_on_ids": [str(add_on_item.pk)]},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(self.order.items.get(item=self.food_item).qty, Decimal("1"))
        self.assertEqual(self.order.items.get(item=add_on_item).qty, Decimal("1"))
        self.assertEqual(response["HX-Trigger"], "close-add-on-dialog")

    def test_add_on_item_remains_pickable_from_catalog(self):
        add_on_item = Item.objects.create(
            item_name="Extra Sauce",
            item_group=self.group_food,
            stock_uom=self.uom,
            department="FOOD",
            is_sales_item=True,
        )
        MenuItem.objects.create(menu=self.menu, item=add_on_item, rate=Decimal("300"))
        ItemAddOn.objects.create(parent_item=self.food_item, add_on_item=add_on_item)

        response = self.client.get(reverse("pos:pos_order_screen", kwargs={"pk": self.order.pk}))

        self.assertContains(response, add_on_item.item_name)
        self.assertContains(response, "Add-ons")

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


class POSCatalogFilterTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self._open_shift()
        self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        self.order = Order.objects.first()
        self.order_url = reverse("pos:pos_order_screen", kwargs={"pk": self.order.pk})

    def test_catalog_search_includes_match_and_excludes_non_match(self):
        response = self.client.get(self.order_url, {"q": "Coke"})

        self.assertEqual(response.context["catalog_query"], "Coke")
        self.assertContains(response, "Coke")
        self.assertNotContains(response, "Jollof Rice")

    def test_catalog_category_and_special_filters(self):
        category_response = self.client.get(self.order_url, {"group": self.group_food.name})

        self.assertEqual(category_response.context["catalog_group"], self.group_food.name)
        self.assertContains(category_response, "Jollof Rice")
        self.assertNotContains(category_response, "Coke")

        self.drink_menu_item.special_dish = True
        self.drink_menu_item.save(update_fields=["special_dish"])
        specials_response = self.client.get(self.order_url, {"specials": "1"})

        self.assertTrue(specials_response.context["catalog_specials"])
        self.assertContains(specials_response, "Coke")
        self.assertNotContains(specials_response, "Jollof Rice")

    def test_htmx_catalog_filter_returns_only_catalog_workspace(self):
        response = self.client.get(
            self.order_url,
            {"q": "Coke"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="catalog-workspace",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="catalog-workspace"')
        self.assertNotContains(response, 'id="pos-main"')
        self.assertNotContains(response, 'id="cart-panel"')
        self.assertContains(response, "Coke")
        self.assertNotContains(response, "Jollof Rice")

    def test_full_order_url_restores_catalog_filters(self):
        response = self.client.get(
            self.order_url,
            {"q": "Coke", "group": self.group_drinks.name, "specials": "1"},
        )

        self.assertEqual(response.context["catalog_query"], "Coke")
        self.assertEqual(response.context["catalog_group"], self.group_drinks.name)
        self.assertTrue(response.context["catalog_specials"])
        self.assertContains(response, "Coke")
        self.assertNotContains(response, "Jollof Rice")

    def test_clear_filters_resets_catalog_and_header_state(self):
        filtered_response = self.client.get(self.order_url, {"q": "Coke"})
        clear_response = self.client.get(
            self.order_url,
            {"clear_filters": "1"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="catalog-workspace",
        )

        self.assertContains(filtered_response, "Clear filters")
        self.assertContains(filtered_response, f'hx-push-url="{self.order_url}"')
        self.assertFalse(clear_response.context["catalog_has_filters"])
        self.assertContains(clear_response, 'id="catalog-search"')
        self.assertContains(clear_response, 'value=""')
        self.assertContains(clear_response, "Coke")
        self.assertContains(clear_response, "Jollof Rice")

        content = clear_response.content.decode()
        self.assertLess(content.index('id="catalog-workspace"'), content.index('id="catalog-search-field"'))

    def test_cart_mutation_preserves_filtered_catalog_oob_result(self):
        response = self.client.post(
            reverse("pos:pos_order_add_item", kwargs={"pk": self.order.pk}),
            {
                "item_id": self.food_item.pk,
                "qty": "1",
                "q": "Coke",
                "group": "",
                "specials": "",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["catalog_query"], "Coke")
        self.assertEqual([item.item_id for item in response.context["menu_items"]], [self.drink_item.pk])
        self.assertContains(response, 'hx-swap-oob="outerHTML"')
        self.assertContains(response, "Jollof Rice")
        self.assertContains(response, "Coke")


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
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger["showMessages"][0]["message"], "Sent 1 ticket to kitchen & bar.")

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
        trigger = json.loads(response["HX-Trigger"])
        self.assertIn("Kitchen ticket reprinted.", [message["message"] for message in trigger["showMessages"]])
        self.assertTrue(any(message["level"] == "success" for message in trigger["showMessages"]))

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

    def _add_bank_mode(self):
        bank, _ = ModeOfPayment.objects.get_or_create(name="Bank", defaults={"type": "BANK"})
        PaymentGLMapping.objects.get_or_create(mode_of_payment=bank, defaults={"default_account": "Bank Account"})
        OpeningPayment.objects.create(
            opening_entry=self.order.opening_entry,
            mode_of_payment=bank,
            opening_amount=Decimal("0"),
        )
        return bank

    def test_payment_dialog_renders_split_payment_and_discount_placeholder(self):
        response = self.client.get(
            reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}),
            HTTP_HX_REQUEST="true",
        )

        self.assertContains(response, "Apply Discount")
        self.assertContains(response, "Not available yet")
        self.assertContains(response, "Total Entered")
        self.assertContains(response, "Order Summary")
        self.assertContains(response, "Discount")
        self.assertContains(response, "₦0.00")
        self.assertContains(response, f'name="payment_{self.cash.pk}"')
        self.assertNotContains(response, 'name="discount"')

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

    def test_settle_ignores_zero_electronic_field_when_cash_is_paid(self):
        bank = self._add_bank_mode()

        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}),
            {f"payment_{bank.pk}": "0", f"payment_{self.cash.pk}": "3000"},
        )

        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "SUBMITTED")
        self.assertEqual(self.order.payments.count(), 1)
        self.assertEqual(self.order.payments.get().mode_of_payment, self.cash)

    def test_settle_accepts_electronic_payment_without_reference(self):
        bank = self._add_bank_mode()

        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}),
            {f"payment_{bank.pk}": "3000"},
        )

        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "SUBMITTED")
        self.assertEqual(self.order.payments.get().reference_no, "")

    def test_settle_takeaway_no_print_needed(self):
        order = Order.objects.create(
            order_type="TAKE_AWAY",
            opening_entry=POSOpeningEntry.objects.filter(status=POSOpeningEntry.SUBMITTED).first(),
        )
        add_order_line(order, self.food_item, qty=1, rate=Decimal("1500"))
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

    def test_settle_auto_creates_tickets(self):
        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}), {f"payment_{self.cash.pk}": "3000"}
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "SUBMITTED")
        self.assertEqual(self.order.kots.count(), 1)
        kot = self.order.kots.get()
        self.assertEqual(kot.type, "New Order")
        self.assertEqual(kot.print_status, "PRINTED")
        self.assertEqual(kot.created_by, self.user)
        self.assertEqual(kot.order_number, self.order.order_number)
        events = list(self.order.audit_events.order_by("pk").values_list("event_type", flat=True))
        self.assertIn("KOTS_CREATED", events)
        self.assertEqual(events[-1], "SUBMITTED")

    def test_settle_existing_tickets_no_duplicates(self):
        self.client.post(reverse("pos:pos_order_sync", kwargs={"pk": self.order.pk}))
        ticket_count = self.order.kots.count()
        self.assertEqual(ticket_count, 1)
        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}), {f"payment_{self.cash.pk}": "3000"}
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "SUBMITTED")
        self.assertEqual(self.order.kots.count(), ticket_count)

    def test_settle_skips_when_no_ticket_required(self):
        production_unit = ProductionUnit.objects.get(department="FOOD")
        production_unit.block_takeaway_kot = True
        production_unit.save(update_fields=["block_takeaway_kot"])
        order = Order.objects.create(
            order_type="TAKE_AWAY",
            opening_entry=POSOpeningEntry.objects.filter(status=POSOpeningEntry.SUBMITTED).first(),
        )
        add_order_line(order, self.food_item, qty=1, rate=Decimal("1500"))
        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": order.pk}), {f"payment_{self.cash.pk}": "1500"}
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "SUBMITTED")
        self.assertEqual(order.kots.count(), 0)

    def test_settle_missing_production_unit_blocks(self):
        ProductionUnit.objects.filter(department="FOOD").delete()
        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}), {f"payment_{self.cash.pk}": "3000"}
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "DRAFT")
        self.assertEqual(self.order.payments.count(), 0)
        self.assertEqual(self.order.kots.count(), 0)

    def test_retry_submitted_pending_ticket(self):
        with patch(
            "apps.orders.services.printing.print_ticket",
            return_value=PrintResult(success=False, ticket_type="kitchen"),
        ):
            response = self.client.post(
                reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}), {f"payment_{self.cash.pk}": "3000"}
            )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        kot = self.order.kots.get()
        self.assertEqual(kot.print_status, "PENDING")
        response = self.client.post(
            reverse(
                "pos:pos_order_ticket_print",
                kwargs={"pk": self.order.pk, "ticket_type": "kitchen", "action": "retry"},
            )
        )
        self.assertEqual(response.status_code, 302)
        kot.refresh_from_db()
        self.assertEqual(kot.print_status, "PRINTED")

    def test_retry_submitted_no_pending_ticket(self):
        response = self.client.post(
            reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}), {f"payment_{self.cash.pk}": "3000"}
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.post(
            reverse(
                "pos:pos_order_ticket_print",
                kwargs={"pk": self.order.pk, "ticket_type": "kitchen", "action": "retry"},
            ),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No kitchen ticket is ready for that action.")

    def test_history_detail_retry_button_submitted(self):
        with patch(
            "apps.orders.services.printing.print_ticket",
            return_value=PrintResult(success=False, ticket_type="kitchen"),
        ):
            self.client.post(
                reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}), {f"payment_{self.cash.pk}": "3000"}
            )
        self.order.refresh_from_db()
        response = self.client.get(reverse("pos:pos_order_history_detail", kwargs={"pk": self.order.pk}))
        self.assertContains(response, "Retry kitchen ticket")
        self.client.post(
            reverse(
                "pos:pos_order_ticket_print",
                kwargs={"pk": self.order.pk, "ticket_type": "kitchen", "action": "retry"},
            )
        )
        response = self.client.get(reverse("pos:pos_order_history_detail", kwargs={"pk": self.order.pk}))
        self.assertNotContains(response, "Retry kitchen ticket")


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

    def test_cancel_empty_draft_rejected(self):
        self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        empty = Order.objects.filter(status="DRAFT").exclude(pk=self.order.pk).first()
        self.assertIsNotNone(empty)
        response = self.client.post(
            reverse("pos:pos_order_cancel", kwargs={"pk": empty.pk}),
            {"cancel_reason": "cashier_error", "cancel_reason_note": ""},
        )
        self.assertEqual(response.status_code, 302)
        empty.refresh_from_db()
        self.assertEqual(empty.status, "DRAFT")

    def test_discard_empty_draft(self):
        self.client.post(reverse("pos:pos_order_new"), {"order_type": "DINE_IN", "guest_count": "1"})
        empty = Order.objects.filter(status="DRAFT").exclude(pk=self.order.pk).first()
        self.assertIsNotNone(empty)
        response = self.client.post(
            reverse("pos:pos_order_discard", kwargs={"pk": empty.pk}),
        )
        self.assertEqual(response.status_code, 302)
        empty.refresh_from_db()
        self.assertEqual(empty.status, "DISCARDED")
        self.assertEqual(empty.discarded_by, self.user)
        self.assertIsNotNone(empty.discarded_at)

    def test_discard_order_with_items_rejected(self):
        response = self.client.post(
            reverse("pos:pos_order_discard", kwargs={"pk": self.order.pk}),
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
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger["showMessages"][0]["message"], "Receipt printed successfully.")
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
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger["showMessages"][0]["message"], "Receipt reprinted successfully.")
        self.assertContains(response, "Reprint Receipt")

    @patch("apps.orders.views_pos.printing.print_receipt")
    def test_failed_receipt_print_still_claims_printed_state(self, print_receipt):
        """DB claim happens before the agent so a successful print cannot leave state unprinted."""
        print_receipt.return_value = PrintResult(success=False, ticket_type="receipt")
        response = self.client.post(
            reverse("pos:pos_order_print", kwargs={"pk": self.order.pk}), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.invoice_printed)
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
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger["showMessages"][0]["message"], "Receipt printed successfully.")


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
        response = self.client.post(
            reverse("pos:pos_order_clear", kwargs={"pk": self.order.pk}),
            HTTP_HX_REQUEST="true",
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.kots.count(), 0)
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger["showMessages"][0]["message"], "Order cleared.")

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
        self.assertContains(response, "Customer #1")
        self.assertContains(response, "Customer #2")

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
        self.assertContains(response, "Customer #1")
        self.assertContains(response, "Customer #2")
        self.assertEqual(
            [group["subtotal"] for group in response.context["guest_groups"]], [Decimal("1500"), Decimal("1500")]
        )

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

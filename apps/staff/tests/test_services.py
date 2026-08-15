"""Direct service-level tests for staff workflows — shift opening and closing math."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.orders.models import Order
from apps.orders.services import add_order_line, settle_order
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import ProductionUnit, Restaurant
from apps.users.models import CustomUser

from ..models import ClosingPayment, OpeningPayment, POSClosingEntry, POSOpeningEntry
from ..services import expected_closing_amounts, open_shift, submit_closing_entry


class OpenShiftTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(company="Test Co")
        cls.cash, _ = ModeOfPayment.objects.get_or_create(name="Cash", defaults={"type": "CASH"})
        cls.card, _ = ModeOfPayment.objects.get_or_create(name="Card", defaults={"type": "BANK", "enabled": True})
        PaymentGLMapping.objects.get_or_create(mode_of_payment=cls.card, defaults={"default_account": "Bank Account"})
        cls.user = CustomUser.objects.create_user(username="cashier", password="testpass123")

    def test_opens_shift_with_float_and_remarks(self):
        entry = open_shift(self.user, {self.cash: Decimal("50000"), self.card: Decimal("0")}, remarks="  Ready  ")
        self.assertEqual(entry.status, "SUBMITTED")
        self.assertTrue(entry.is_open)
        self.assertEqual(entry.remarks, "Ready")
        self.assertEqual(entry.opening_payments.count(), 2)
        self.assertEqual(entry.opening_payments.get(mode_of_payment=self.cash).opening_amount, Decimal("50000"))

    def test_second_shift_blocked(self):
        open_shift(self.user, {self.cash: Decimal("50000")})
        with self.assertRaisesMessage(ValidationError, "A shift is already open."):
            open_shift(self.user, {self.cash: Decimal("10000")})

    def test_missing_settings_blocked(self):
        Restaurant.objects.all().delete()
        with self.assertRaisesMessage(ValidationError, "Restaurant settings are not configured."):
            open_shift(self.user, {self.cash: Decimal("50000")})


class ExpectedClosingAmountsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.inventory.models import UOM, Item, ItemGroup, Warehouse
        from apps.menu.models import Menu, MenuItem

        cls.restaurant = Restaurant.objects.create(company="Test Co")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.warehouse = Warehouse.objects.create(name="Kitchen")
        cls.item = Item.objects.create(
            item_name="Jollof Rice", item_group=cls.group, stock_uom=cls.uom, department="FOOD", is_sales_item=True
        )
        cls.menu = Menu.objects.create(name="Main Menu")
        cls.menu_item = MenuItem.objects.create(menu=cls.menu, item=cls.item, rate=Decimal("1500"))
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.default_warehouse = cls.warehouse
        cls.restaurant.save()
        ProductionUnit.objects.create(name="Kitchen", warehouse=cls.warehouse, department="FOOD")
        cls.cash, _ = ModeOfPayment.objects.get_or_create(name="Cash", defaults={"type": "CASH"})
        cls.card, _ = ModeOfPayment.objects.get_or_create(name="Card", defaults={"type": "BANK", "enabled": True})
        for mode in (cls.cash, cls.card):
            PaymentGLMapping.objects.get_or_create(
                mode_of_payment=mode, defaults={"default_account": f"{mode.name} Account"}
            )
        cls.user = CustomUser.objects.create_user(username="cashier", password="testpass123")
        cls.opening = POSOpeningEntry.objects.create(cashier=cls.user)
        OpeningPayment.objects.create(
            opening_entry=cls.opening, mode_of_payment=cls.cash, opening_amount=Decimal("50000")
        )
        OpeningPayment.objects.create(opening_entry=cls.opening, mode_of_payment=cls.card, opening_amount=Decimal("0"))
        cls.opening.submit()

    def _expected_rows(self):
        return {
            row["mode"].pk: row
            for row in expected_closing_amounts(self.opening, self.opening.period_start_date, timezone.now())
        }

    def _settle(self, amount, mode):
        order = Order.objects.create(opening_entry=self.opening)
        add_order_line(order, self.item, qty=1, rate=amount)
        settle_order(order, [{"mode_of_payment": mode.pk, "amount": str(amount)}], cashier=self.user)
        return order

    def test_expected_is_opening_plus_collected_per_mode(self):
        self._settle(Decimal("3000"), self.cash)
        self._settle(Decimal("2000"), self.card)
        rows = self._expected_rows()
        self.assertEqual(rows[self.cash.pk]["expected_amount"], Decimal("53000"))
        self.assertEqual(rows[self.card.pk]["expected_amount"], Decimal("2000"))

    def test_cash_change_nets_off_expected(self):
        order = Order.objects.create(opening_entry=self.opening)
        add_order_line(order, self.item, qty=1, rate=Decimal("1500"))
        settle_order(order, [{"mode_of_payment": self.cash.pk, "amount": "2000"}], cashier=self.user)
        rows = self._expected_rows()
        # 50000 float + 2000 paid − 500 change = 51500
        self.assertEqual(rows[self.cash.pk]["expected_amount"], Decimal("51500"))


class SubmitClosingEntryTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.inventory.models import UOM, Item, ItemGroup, Warehouse
        from apps.menu.models import Menu, MenuItem

        cls.restaurant = Restaurant.objects.create(company="Test Co")
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.warehouse = Warehouse.objects.create(name="Kitchen")
        cls.item = Item.objects.create(
            item_name="Jollof Rice", item_group=cls.group, stock_uom=cls.uom, department="FOOD", is_sales_item=True
        )
        cls.menu = Menu.objects.create(name="Main Menu")
        cls.menu_item = MenuItem.objects.create(menu=cls.menu, item=cls.item, rate=Decimal("1500"))
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.default_warehouse = cls.warehouse
        cls.restaurant.save()
        ProductionUnit.objects.create(name="Kitchen", warehouse=cls.warehouse, department="FOOD")
        cls.cash, _ = ModeOfPayment.objects.get_or_create(name="Cash", defaults={"type": "CASH"})
        PaymentGLMapping.objects.get_or_create(mode_of_payment=cls.cash, defaults={"default_account": "Cash Account"})
        cls.user = CustomUser.objects.create_user(username="cashier", password="testpass123")
        cls.opening = POSOpeningEntry.objects.create(cashier=cls.user)
        OpeningPayment.objects.create(
            opening_entry=cls.opening, mode_of_payment=cls.cash, opening_amount=Decimal("50000")
        )
        cls.opening.submit()

    def test_submit_closes_shift_and_records_difference(self):
        order = Order.objects.create(opening_entry=self.opening)
        add_order_line(order, self.item, qty=1, rate=Decimal("1500"))
        settle_order(order, [{"mode_of_payment": self.cash.pk, "amount": "1500"}], cashier=self.user)

        closing = POSClosingEntry.objects.create(opening_entry=self.opening, cashier=self.user)
        ClosingPayment.objects.create(closing_entry=closing, mode_of_payment=self.cash, closing_amount=Decimal("51200"))
        submit_closing_entry(closing)

        closing.refresh_from_db()
        self.assertEqual(closing.status, "SUBMITTED")
        cp = closing.closing_payments.get(mode_of_payment=self.cash)
        self.assertEqual(cp.expected_amount, Decimal("51500"))
        self.assertEqual(closing.total_short_excess, Decimal("-300"))
        self.opening.refresh_from_db()
        self.assertFalse(self.opening.is_open)
        self.assertEqual(self.opening.closing_entry_id, closing.pk)

    def test_draft_orders_block_close(self):
        Order.objects.create(opening_entry=self.opening)
        closing = POSClosingEntry.objects.create(opening_entry=self.opening, cashier=self.user)
        ClosingPayment.objects.create(closing_entry=closing, mode_of_payment=self.cash, closing_amount=Decimal("0"))
        with self.assertRaises(ValidationError):
            submit_closing_entry(closing)

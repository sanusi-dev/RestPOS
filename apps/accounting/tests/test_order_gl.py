"""Order GL tests — settle legs, departmental income split, change, rounding, COGS,
cancel reversal, missing-account failures, fiscal year guard."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounting.models import FiscalYear, GLEntry, LedgerAccount
from apps.inventory.models import UOM, Bin, Item, ItemGroup, StockLedgerEntry, Warehouse
from apps.menu.models import Menu, MenuItem
from apps.orders.models import Order, OrderItem
from apps.orders.services import (
    add_order_line,
    make_return,
    settle_order,
    submit_return,
)
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import ProductionUnit, Restaurant
from apps.staff.models import OpeningPayment, POSOpeningEntry
from apps.users.models import CustomUser

from .helpers import setup_chart_of_accounts


class OrderGLTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(company="Test Co")
        cls.accounts = setup_chart_of_accounts(cls.restaurant)
        cls.uom = UOM.objects.create(name="Nos")
        cls.group_food = ItemGroup.objects.create(
            name="Food", income_account=cls.accounts["food_sales"], expense_account=cls.accounts["cogs"]
        )
        cls.group_drinks = ItemGroup.objects.create(
            name="Beverages", income_account=cls.accounts["drinks_sales"], expense_account=cls.accounts["cogs"]
        )
        cls.kitchen_wh = Warehouse.objects.create(name="Kitchen", account=cls.accounts["cogs"])
        cls.bar_wh = Warehouse.objects.create(name="Bar", account=cls.accounts["cash"])  # placeholder, fixed below
        cls.bar_wh.account = LedgerAccount.objects.create(
            name="Stock in Hand — Bar",
            parent=cls.accounts["assets"],
            root_type=LedgerAccount.ASSET,
            report_type=LedgerAccount.BALANCE_SHEET,
            account_type=LedgerAccount.ACCOUNT_TYPE_STOCK,
        )
        cls.bar_wh.save()
        cls.food = Item.objects.create(
            item_name="Jollof Rice",
            item_group=cls.group_food,
            stock_uom=cls.uom,
            department="FOOD",
            is_sales_item=True,
        )
        cls.drink = Item.objects.create(
            item_name="Coke",
            item_group=cls.group_drinks,
            stock_uom=cls.uom,
            department="DRINKS",
            is_sales_item=True,
        )
        cls.menu = Menu.objects.create(name="Main")
        cls.food_mi = MenuItem.objects.create(menu=cls.menu, item=cls.food, rate=Decimal("1500"))
        cls.drink_mi = MenuItem.objects.create(menu=cls.menu, item=cls.drink, rate=Decimal("500"))
        Bin.objects.create(item=cls.food, warehouse=cls.kitchen_wh, actual_qty=Decimal("100"))
        Bin.objects.create(item=cls.drink, warehouse=cls.bar_wh, actual_qty=Decimal("100"))
        cls.cash, _ = ModeOfPayment.objects.get_or_create(name="Cash", defaults={"type": "CASH"})
        cls.bank, _ = ModeOfPayment.objects.get_or_create(name="Bank", defaults={"type": "BANK"})
        PaymentGLMapping.objects.get_or_create(
            mode_of_payment=cls.cash, defaults={"default_account": cls.accounts["cash"]}
        )
        PaymentGLMapping.objects.get_or_create(
            mode_of_payment=cls.bank, defaults={"default_account": cls.accounts["bank"]}
        )
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.default_warehouse = cls.bar_wh
        cls.restaurant.save()
        cls.user = CustomUser.objects.create_user(username="cashier", password="testpass123")
        cls.opening = POSOpeningEntry.objects.create(cashier=cls.user)
        OpeningPayment.objects.create(
            opening_entry=cls.opening, mode_of_payment=cls.cash, opening_amount=Decimal("50000")
        )
        cls.opening.submit()
        cls.kitchen = ProductionUnit.objects.create(name="Kitchen", warehouse=cls.kitchen_wh, department="FOOD")
        cls.bar = ProductionUnit.objects.create(name="Bar", warehouse=cls.bar_wh, department="DRINKS")

    def _create_order(self, **kwargs):
        defaults = {"opening_entry": self.opening}
        defaults.update(kwargs)
        return Order.objects.create(**defaults)

    def _settle(self, order, amount=None):
        order.recalculate_totals()
        amount = amount or order.rounded_total
        settle_order(
            order,
            [{"mode_of_payment": self.cash.pk, "amount": amount}],
            cashier=self.user,
        )
        order.refresh_from_db()
        return order

    def _order_gl(self, order):
        return GLEntry.objects.filter(voucher_type="Order", voucher_no=order.invoice_number)


class OrderSettleGLTest(OrderGLTestBase):
    def test_settle_posts_income_and_payment_legs(self):
        order = self._create_order()
        add_order_line(order, self.food, qty=1, rate=Decimal("1500"), menu_item=self.food_mi)
        self._settle(order)
        entries = self._order_gl(order)
        self.assertEqual(entries.count(), 2)
        cash_entry = entries.get(account=self.accounts["cash"])
        self.assertEqual(cash_entry.debit, Decimal("1500"))
        income_entry = entries.get(account=self.accounts["food_sales"])
        self.assertEqual(income_entry.credit, Decimal("1500"))

    def test_departmental_income_split(self):
        order = self._create_order()
        add_order_line(order, self.food, qty=1, rate=Decimal("1500"), menu_item=self.food_mi)
        add_order_line(order, self.drink, qty=1, rate=Decimal("500"), menu_item=self.drink_mi)
        self._settle(order)
        entries = self._order_gl(order)
        self.assertEqual(entries.get(account=self.accounts["food_sales"]).credit, Decimal("1500"))
        self.assertEqual(entries.get(account=self.accounts["drinks_sales"]).credit, Decimal("500"))

    def test_change_reduces_cash_leg(self):
        order = self._create_order()
        add_order_line(order, self.food, qty=1, rate=Decimal("1500"), menu_item=self.food_mi)
        self._settle(order, amount=Decimal("2000"))  # 500 change
        cash_entry = self._order_gl(order).get(account=self.accounts["cash"])
        self.assertEqual(cash_entry.debit, Decimal("1500"))

    def test_rounding_posts_round_off(self):
        order = self._create_order()
        add_order_line(order, self.food, qty=1, rate=Decimal("1499.50"), menu_item=self.food_mi)
        order.recalculate_totals()
        # rounding_adjustment = 0.50
        self._settle(order)
        entries = self._order_gl(order)
        round_entry = entries.get(account=self.accounts["round_off"])
        self.assertEqual(round_entry.credit, Decimal("0.50"))

    def test_cogs_posts_for_drink_order(self):
        # Build a FIFO queue so the settle-time deduction has a real outgoing value.
        StockLedgerEntry.create_entry(
            item=self.drink,
            warehouse=self.bar_wh,
            actual_qty=Decimal("100"),
            voucher_type="Purchase Receipt",
            voucher_no="PR-1",
            rate=Decimal("300"),
        )
        order = self._create_order()
        add_order_line(order, self.drink, qty=2, rate=Decimal("500"), menu_item=self.drink_mi)
        self._settle(order)
        entries = self._order_gl(order)
        cogs_entry = entries.get(account=self.accounts["cogs"])
        self.assertEqual(cogs_entry.debit, Decimal("600"))  # 2 × 300
        stock_entry = entries.get(account=self.bar_wh.account)
        self.assertEqual(stock_entry.credit, Decimal("600"))

    def test_missing_income_account_raises(self):
        # Clear both the item-group override and the Restaurant default so the
        # chain resolution has nothing to fall back on.
        self.group_food.income_account = None
        self.group_food.save()
        self.restaurant.default_income_account = None
        self.restaurant.save()
        order = self._create_order()
        add_order_line(order, self.food, qty=1, rate=Decimal("1500"), menu_item=self.food_mi)
        with self.assertRaisesMessage(ValidationError, "default income account"):
            self._settle(order)

    def test_fiscal_year_missing_raises(self):
        FiscalYear.objects.all().delete()
        order = self._create_order()
        add_order_line(order, self.food, qty=1, rate=Decimal("1500"), menu_item=self.food_mi)
        with self.assertRaises(ValidationError):
            self._settle(order)


class OrderCancelGLTest(OrderGLTestBase):
    def test_reverse_order_gl_posts_mirrored_entries(self):
        order = self._create_order()
        add_order_line(order, self.food, qty=1, rate=Decimal("1500"), menu_item=self.food_mi)
        self._settle(order)
        # Paid orders cannot be cancelled via cancel_order; the reversal is
        # invoked directly (as the refund flow does) and must mirror the
        # settle legs.
        from apps.accounting.services import reverse_order_gl

        reverse_order_gl(order)
        entries = self._order_gl(order)
        self.assertEqual(entries.filter(is_cancelled=True).count(), 2)
        self.assertEqual(entries.filter(is_cancelled=False).count(), 2)
        reversal = entries.filter(is_cancelled=False, account=self.accounts["cash"]).first()
        self.assertEqual(reversal.credit, Decimal("1500"))

    def test_reverse_order_gl_posts_on_today_not_sale_date(self):
        # Corrections post on the day they occur; a stale sale date must not
        # reach the GL (and would fail the fiscal-year guard if it did not
        # fall inside an enabled year).
        order = self._create_order()
        add_order_line(order, self.food, qty=1, rate=Decimal("1500"), menu_item=self.food_mi)
        self._settle(order)
        FiscalYear.objects.create(
            name="FY2020",
            year_start_date=date(2020, 1, 1),
            year_end_date=date(2020, 12, 31),
        )
        from apps.accounting.services import reverse_order_gl

        reverse_order_gl(order, posting_date=date(2020, 3, 15))
        reversals = self._order_gl(order).filter(is_cancelled=False)
        self.assertTrue(reversals.exists())
        self.assertEqual(set(reversals.values_list("posting_date", flat=True)), {date(2020, 3, 15)})


class RefundGLTest(OrderGLTestBase):
    def test_return_posts_mirrored_refund(self):
        order = self._create_order()
        add_order_line(order, self.food, qty=1, rate=Decimal("1500"), menu_item=self.food_mi)
        self._settle(order)
        ret = make_return(order)
        ret.recalculate_totals()
        submit_return(ret, actor=self.user)
        ret.refresh_from_db()
        entries = self._order_gl(ret)
        self.assertEqual(entries.count(), 2)
        self.assertEqual(entries.get(account=self.accounts["food_sales"]).debit, Decimal("1500"))
        self.assertEqual(entries.get(account=self.accounts["cash"]).credit, Decimal("1500"))

    def test_partial_return_posts_proportion(self):
        order = self._create_order()
        add_order_line(order, self.food, qty=2, rate=Decimal("1500"), menu_item=self.food_mi)
        self._settle(order)
        ret = make_return(order)
        # Reduce one line to half (qty -1 of -2)
        line = ret.items.first()
        line.qty = Decimal("-1")
        line.save()
        ret.recalculate_totals()
        submit_return(ret, actor=self.user)
        ret.refresh_from_db()
        entries = self._order_gl(ret)
        self.assertEqual(entries.get(account=self.accounts["food_sales"]).debit, Decimal("1500"))

    def test_second_return_after_first_submitted(self):
        order = self._create_order()
        add_order_line(order, self.food, qty=4, rate=Decimal("1500"), menu_item=self.food_mi)
        self._settle(order)
        # First return refunds half (qty -2 of -4).
        ret1 = make_return(order)
        line1 = ret1.items.first()
        line1.qty = Decimal("-2")
        line1.save()
        ret1.recalculate_totals()
        submit_return(ret1, actor=self.user)
        # Second return mirrors only the remaining qty (-2), allowed once the
        # first is SUBMITTED.
        ret2 = make_return(order)
        self.assertEqual(abs(ret2.items.first().qty), Decimal("2"))
        ret2.recalculate_totals()
        submit_return(ret2, actor=self.user)
        # Both refunds posted
        self.assertEqual(GLEntry.objects.filter(voucher_no=ret2.invoice_number).count(), 2)

    def test_cumulative_qty_cap_enforced(self):
        order = self._create_order()
        add_order_line(order, self.food, qty=2, rate=Decimal("1500"), menu_item=self.food_mi)
        self._settle(order)
        ret1 = make_return(order)
        ret1.recalculate_totals()
        submit_return(ret1, actor=self.user)
        # A full return leaves no remaining quantity; a second return draft
        # has no lines and cannot be submitted.
        ret2 = make_return(order)
        self.assertEqual(ret2.items.count(), 0)
        with self.assertRaisesMessage(ValidationError, "no refundable value"):
            submit_return(ret2, actor=self.user)


class NotRestockableConstraintTest(OrderGLTestBase):
    def test_non_return_line_cannot_be_marked_not_restockable(self):
        from django.db import IntegrityError, transaction

        order = self._create_order()
        add_order_line(order, self.food, qty=1, rate=Decimal("1500"), menu_item=self.food_mi)
        line = order.items.first()
        line.not_restockable = True
        with self.assertRaises(ValidationError):
            line.full_clean()
        # The DB constraint is the last line of defence (bypassing save()).
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrderItem.objects.filter(pk=line.pk).update(not_restockable=True)

    def test_return_line_can_be_marked_not_restockable(self):
        order = self._create_order()
        add_order_line(order, self.food, qty=1, rate=Decimal("1500"), menu_item=self.food_mi)
        self._settle(order)
        ret = make_return(order)
        line = ret.items.first()
        line.not_restockable = True
        line.save(update_fields=["not_restockable", "updated_at"])
        self.assertTrue(OrderItem.objects.get(pk=line.pk).not_restockable)

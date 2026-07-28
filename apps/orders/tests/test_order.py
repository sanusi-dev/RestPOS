from decimal import Decimal

from django.test import TestCase

from apps.inventory.models import UOM, Bin, Item, ItemGroup, StockLedgerEntry, Warehouse
from apps.menu.models import Menu, MenuItem
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import Branch, POSProfile, Restaurant, Room, TaxRate, TaxTemplate

from ..models import Order


class OrderTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.restaurant = Restaurant.objects.create(company="Test Co", branch=cls.branch, default_room=cls.room)
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.warehouse = Warehouse.objects.create(name="Kitchen", branch=cls.branch)
        cls.item = Item.objects.create(
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_sales_item=True,
        )
        cls.item2 = Item.objects.create(
            item_name="Coke",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="DRINKS",
            is_sales_item=True,
        )
        cls.menu = Menu.objects.create(name="Main Menu", branch=cls.branch)
        cls.menu_item = MenuItem.objects.create(menu=cls.menu, item=cls.item, rate=Decimal("1500"))
        cls.menu_item2 = MenuItem.objects.create(menu=cls.menu, item=cls.item2, rate=Decimal("500"))
        cls.cash = ModeOfPayment.objects.get(name="Cash")
        cls.bank = ModeOfPayment.objects.create(name="Test Bank", type="BANK")
        PaymentGLMapping.objects.create(mode_of_payment=cls.cash, default_account="Cash Account")
        PaymentGLMapping.objects.create(mode_of_payment=cls.bank, default_account="Bank Account")
        cls.tax_template = TaxTemplate.objects.create(title="VAT 7.5%", company="Test Co")
        TaxRate.objects.create(
            tax_template=cls.tax_template,
            charge_type="ON_NET_TOTAL",
            rate=Decimal("7.5"),
            account_head="VAT Payable",
            description="VAT 7.5%",
        )
        cls.restaurant.active_menu = cls.menu
        cls.restaurant.default_tax_template = cls.tax_template
        cls.restaurant.save()
        cls.profile = POSProfile.objects.create(name="Main POS", warehouse=cls.warehouse)
        POSProfile.payments.through.objects.create(
            pos_profile=cls.profile,
            mode_of_payment=cls.cash,
            is_default=True,
        )


class OrderModelTest(OrderTestBase):
    def test_create_order(self):
        order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            pos_profile=self.profile,
        )
        self.assertEqual(order.status, "DRAFT")
        self.assertTrue(order.invoice_number.startswith("REST-"))

    def test_add_item(self):
        order = Order.objects.create(restaurant=self.restaurant, branch=self.branch, pos_profile=self.profile)
        order.add_item(self.item, qty=2, rate=Decimal("1500"))
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().qty, Decimal("2"))
        order.recalculate_totals()
        self.assertTrue(order.net_total > 0)

    def test_add_item_increments_existing(self):
        order = Order.objects.create(restaurant=self.restaurant, branch=self.branch, pos_profile=self.profile)
        order.add_item(self.item, qty=1, rate=Decimal("1500"))
        order.add_item(self.item, qty=1, rate=Decimal("1500"))
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().qty, Decimal("2"))

    def test_remove_item(self):
        order = Order.objects.create(restaurant=self.restaurant, branch=self.branch, pos_profile=self.profile)
        order.add_item(self.item, qty=1, rate=Decimal("1500"))
        oi_pk = order.items.first().pk
        order.remove_item(oi_pk)
        self.assertEqual(order.items.count(), 0)

    def test_guest_count_defaults_to_one(self):
        order = Order.objects.create(restaurant=self.restaurant, branch=self.branch, pos_profile=self.profile)
        self.assertEqual(order.guest_count, 1)

    def test_status_default_is_draft(self):
        order = Order.objects.create(restaurant=self.restaurant, branch=self.branch, pos_profile=self.profile)
        self.assertEqual(order.status, "DRAFT")

    def test_str(self):
        order = Order.objects.create(restaurant=self.restaurant, branch=self.branch, pos_profile=self.profile)
        self.assertIn(order.customer_name, str(order))


class OrderSettleTest(OrderTestBase):
    def setUp(self):
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            pos_profile=self.profile,
        )
        self.order.add_item(self.item, qty=2, rate=Decimal("1500"))

    def test_settle_changes_status(self):
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "3000"}])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "SUBMITTED")
        self.assertTrue(self.order.is_paid)

    def test_settle_calculates_tax(self):
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "3500"}])
        self.order.refresh_from_db()
        self.assertTrue(self.order.total_taxes > 0)
        self.assertEqual(self.order.taxes.count(), 1)

    def test_settle_creates_payments(self):
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "2000"}])
        self.assertEqual(self.order.payments.count(), 1)
        self.assertEqual(self.order.payments.first().amount, Decimal("2000"))

    def test_settle_computes_change(self):
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "5000"}])
        self.order.refresh_from_db()
        self.assertTrue(self.order.change_amount > 0)

    def test_settle_deducts_stock(self):
        Bin.objects.create(item=self.item, warehouse=self.warehouse, actual_qty=Decimal("10"))
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "3500"}])
        sles = StockLedgerEntry.objects.filter(voucher_type="POS Order", voucher_no=str(self.order.pk))
        self.assertTrue(sles.exists())
        self.assertEqual(sles.first().actual_qty, Decimal("-2"))

    def test_settle_skips_non_stock_items(self):
        self.item2.is_stock_item = False
        self.item2.save()
        self.order.add_item(self.item2, qty=1)
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "4000"}])
        sles = StockLedgerEntry.objects.filter(voucher_type="POS Order", voucher_no=str(self.order.pk))
        self.assertEqual(sles.count(), 1)  # only the stock item

    def test_settle_frees_table(self):
        from apps.settings.models import Table

        table = Table.objects.create(name="T1", room=self.room, branch=self.branch)
        self.order.table = table
        self.order.order_type = "DINE_IN"
        self.order.save()
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "3500"}])
        table.refresh_from_db()
        self.assertFalse(table.occupied)


class OrderCancelTest(OrderTestBase):
    def setUp(self):
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            pos_profile=self.profile,
        )
        self.order.add_item(self.item, qty=2, rate=Decimal("1500"))
        self.order.settle([{"mode_of_payment": self.cash.pk, "amount": "3500"}])

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


class KOTTest(OrderTestBase):
    def setUp(self):
        self.order = Order.objects.create(
            restaurant=self.restaurant,
            branch=self.branch,
            pos_profile=self.profile,
        )
        self.order.add_item(self.item, qty=2, rate=Decimal("1500"))
        from apps.settings.models import ProductionUnit

        self.pu = ProductionUnit.objects.create(
            name="Kitchen",
            branch=self.branch,
            warehouse=self.warehouse,
            department="FOOD",
        )

    def test_generate_kot_creates_ticket(self):
        prev = [{"item_id": self.item.pk, "qty": "0", "customer_index": 1, "comments": ""}]
        self.order.generate_kots(prev)
        kots = self.order.kots.filter(status="SUBMITTED")
        self.assertTrue(kots.exists())
        kot = kots.first()
        self.assertEqual(kot.type, "New Order")
        self.assertEqual(kot.production_unit, self.pu)

    def test_no_kot_when_unchanged(self):
        prev = [{"item_id": self.item.pk, "qty": "2", "customer_index": 1, "comments": ""}]
        self.order.generate_kots(prev)
        kots = self.order.kots.filter(status="SUBMITTED").exclude(type="Partially Cancelled")
        self.assertEqual(kots.count(), 0)

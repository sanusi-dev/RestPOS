from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import ItemGroup, Warehouse
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import (
    Branch,
    POSProfile,
    POSProfilePayment,
    Restaurant,
    Room,
)


class POSProfileModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.restaurant = Restaurant.objects.create(company="Test Co", branch=cls.branch, default_room=cls.room)
        cls.warehouse = Warehouse.objects.create(name="Kitchen", branch=cls.branch)
        cls.cash = ModeOfPayment.objects.get(name="Cash")
        PaymentGLMapping.objects.create(mode_of_payment=cls.cash, company="Test Co", default_account="Cash Account")

    def test_str_returns_name(self):
        profile = POSProfile.objects.create(name="Main Cashier", warehouse=self.warehouse)
        self.assertEqual(str(profile), "Main Cashier")

    def test_save_auto_assigns_branch(self):
        profile = POSProfile.objects.create(name="Auto Branch", warehouse=self.warehouse)
        self.assertEqual(profile.branch_id, self.branch.pk)

    def test_save_auto_assigns_restaurant(self):
        profile = POSProfile.objects.create(name="Auto Resto", warehouse=self.warehouse)
        self.assertEqual(profile.restaurant_id, self.restaurant.pk)

    def test_save_auto_assigns_company(self):
        profile = POSProfile.objects.create(name="Auto Co", warehouse=self.warehouse)
        self.assertEqual(profile.company, "Test Co")

    def test_unique_together_restaurant(self):
        POSProfile.objects.create(name="Main Cashier", warehouse=self.warehouse)
        with self.assertRaises(IntegrityError):
            POSProfile.objects.create(name="Other Cashier", warehouse=self.warehouse)

    def test_default_currency_ngn(self):
        profile = POSProfile.objects.create(name="P1", warehouse=self.warehouse)
        self.assertEqual(profile.currency, "NGN")

    def test_default_kot_naming_series(self):
        profile = POSProfile.objects.create(name="P2", warehouse=self.warehouse)
        self.assertEqual(profile.kot_naming_series, "KOT-####")

    def test_delete(self):
        profile = POSProfile.objects.create(name="DelMe", warehouse=self.warehouse)
        pk = profile.pk
        profile.delete()
        self.assertFalse(POSProfile.objects.filter(pk=pk).exists())


class POSProfileCleanTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.restaurant = Restaurant.objects.create(company="Test Co", branch=cls.branch, default_room=cls.room)
        cls.warehouse = Warehouse.objects.create(name="Kitchen", branch=cls.branch)
        cls.cash = ModeOfPayment.objects.get(name="Cash")
        PaymentGLMapping.objects.create(mode_of_payment=cls.cash, company="Test Co", default_account="Cash Account")
        cls.profile = POSProfile.objects.create(name="Main Cashier", warehouse=cls.warehouse)
        POSProfilePayment.objects.create(pos_profile=cls.profile, mode_of_payment=cls.cash, is_default=True)

    def test_clean_passes_with_one_default_payment(self):
        self.profile.clean()

    def test_clean_fails_no_payments(self):
        self.profile.delete()
        profile = POSProfile.objects.create(name="No Pay", warehouse=self.warehouse)
        with self.assertRaises(ValidationError):
            profile.clean()

    def test_clean_fails_multiple_defaults(self):
        bank = ModeOfPayment.objects.create(name="Bank", type="BANK")
        PaymentGLMapping.objects.create(mode_of_payment=bank, company="Test Co", default_account="Bank Account")
        POSProfilePayment.objects.create(pos_profile=self.profile, mode_of_payment=bank, is_default=True)
        with self.assertRaises(ValidationError):
            self.profile.clean()

    def test_clean_fails_no_default_payment(self):
        self.profile.delete()
        profile = POSProfile.objects.create(name="No Default", warehouse=self.warehouse)
        POSProfilePayment.objects.create(pos_profile=profile, mode_of_payment=self.cash, is_default=False)
        with self.assertRaises(ValidationError):
            profile.clean()

    def test_clean_fails_payment_without_gl_mapping(self):
        ungleared = ModeOfPayment.objects.create(name="Ungleared", type="CASH")
        self.profile.delete()
        profile = POSProfile.objects.create(name="No GL", warehouse=self.warehouse)
        POSProfilePayment.objects.create(pos_profile=profile, mode_of_payment=ungleared, is_default=True)
        with self.assertRaises(ValidationError):
            profile.clean()

    def test_clean_passes_with_unique_item_groups(self):
        food = ItemGroup.objects.create(name="Food")
        drinks = ItemGroup.objects.create(name="Drinks")
        self.profile.item_groups.add(food, drinks)
        self.profile.clean()

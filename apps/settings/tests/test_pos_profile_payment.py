from django.db.models.deletion import ProtectedError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import Warehouse
from apps.payments.models import ModeOfPayment
from apps.settings.models import (
    Branch,
    POSProfile,
    POSProfilePayment,
    Restaurant,
    Room,
)


class POSProfilePaymentModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.restaurant = Restaurant.objects.create(company="Test Co", branch=cls.branch, default_room=cls.room)
        cls.warehouse = Warehouse.objects.create(name="Kitchen", branch=cls.branch)
        cls.profile = POSProfile.objects.create(name="Main Cashier", warehouse=cls.warehouse)
        cls.cash = ModeOfPayment.objects.get(name="Cash")
        cls.bank = ModeOfPayment.objects.create(name="Bank", type="BANK")

    def test_create(self):
        link = POSProfilePayment.objects.create(pos_profile=self.profile, mode_of_payment=self.cash, is_default=True)
        self.assertIsNotNone(link.pk)

    def test_str(self):
        link = POSProfilePayment.objects.create(pos_profile=self.profile, mode_of_payment=self.cash)
        self.assertIn("Cash", str(link))
        self.assertIn("Main Cashier", str(link))

    def test_unique_together_profile_mode(self):
        POSProfilePayment.objects.create(pos_profile=self.profile, mode_of_payment=self.cash)
        with self.assertRaises(IntegrityError):
            POSProfilePayment.objects.create(pos_profile=self.profile, mode_of_payment=self.cash)

    def test_is_default_false_by_default(self):
        link = POSProfilePayment.objects.create(pos_profile=self.profile, mode_of_payment=self.cash)
        self.assertFalse(link.is_default)

    def test_allow_in_returns_false_by_default(self):
        link = POSProfilePayment.objects.create(pos_profile=self.profile, mode_of_payment=self.cash)
        self.assertFalse(link.allow_in_returns)

    def test_cascade_delete_on_profile(self):
        link = POSProfilePayment.objects.create(pos_profile=self.profile, mode_of_payment=self.cash)
        self.profile.delete()
        self.assertFalse(POSProfilePayment.objects.filter(pk=link.pk).exists())

    def test_protect_on_mode_delete(self):
        POSProfilePayment.objects.create(pos_profile=self.profile, mode_of_payment=self.cash)
        with self.assertRaises(ProtectedError):
            self.cash.delete()

    def test_ordering_by_mode_name(self):
        POSProfilePayment.objects.create(pos_profile=self.profile, mode_of_payment=self.bank)
        POSProfilePayment.objects.create(pos_profile=self.profile, mode_of_payment=self.cash)
        links = list(POSProfilePayment.objects.all())
        self.assertEqual(links[0].mode_of_payment.name, "Bank")

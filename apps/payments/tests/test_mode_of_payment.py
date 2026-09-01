from django.test import TestCase

from apps.payments.models import ModeOfPayment


class ModeOfPaymentModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cash = ModeOfPayment.objects.create(name="Test Cash", type="CASH")
        cls.bank = ModeOfPayment.objects.create(name="Test Bank", type="BANK")
        cls.phone = ModeOfPayment.objects.create(name="Test USSD", type="PHONE")

    def test_can_dispense_change_only_for_cash(self):
        self.assertTrue(self.cash.can_dispense_change)
        self.assertFalse(self.bank.can_dispense_change)
        self.assertFalse(self.phone.can_dispense_change)


class ModeOfPaymentSeedMigrationTest(TestCase):
    """Verify the 0002 seed migration created the four default payment modes."""

    def test_seed_creates_defaults(self):
        names = set(ModeOfPayment.objects.values_list("name", flat=True))
        self.assertIn("Cash", names)
        self.assertIn("Bank Transfer", names)
        self.assertIn("Card", names)
        self.assertIn("USSD / Mobile Money", names)
        self.assertEqual(ModeOfPayment.objects.get(name="Cash").type, "CASH")
        self.assertEqual(ModeOfPayment.objects.filter(enabled=True).count() >= 4, True)
        self.assertEqual(ModeOfPayment.objects.filter(is_default=True).count(), 1)
        self.assertTrue(ModeOfPayment.objects.get(name="Cash").is_default)

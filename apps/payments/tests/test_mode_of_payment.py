from django.db.utils import IntegrityError
from django.test import TestCase

from apps.payments.models import ModeOfPayment


class ModeOfPaymentModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Use unique test names that don't collide with the seed migration's
        # default payment modes (Cash, Bank Transfer, Card, USSD / Mobile Money).
        cls.cash = ModeOfPayment.objects.create(name="Test Cash", type="CASH")
        cls.bank = ModeOfPayment.objects.create(name="Test Bank", type="BANK")
        cls.phone = ModeOfPayment.objects.create(name="Test USSD", type="PHONE")

    def test_str_returns_name(self):
        self.assertEqual(str(self.cash), "Test Cash")

    def test_name_unique(self):
        with self.assertRaises(IntegrityError):
            ModeOfPayment.objects.create(name="Test Cash", type="CASH")

    def test_type_required_in_form(self):
        """Forms reject blank `type` (CharField with choices is required)."""
        from apps.payments.forms import ModeOfPaymentForm

        form = ModeOfPaymentForm(data={"name": "Test Foo", "type": "", "enabled": "on"})
        self.assertFalse(form.is_valid())
        self.assertIn("type", form.errors)

    def test_can_dispense_change_only_for_cash(self):
        self.assertTrue(self.cash.can_dispense_change)
        self.assertFalse(self.bank.can_dispense_change)
        self.assertFalse(self.phone.can_dispense_change)

    def test_default_enabled(self):
        self.assertTrue(self.cash.enabled)

    def test_disable_mode(self):
        self.bank.enabled = False
        self.bank.save()
        self.bank.refresh_from_db()
        self.assertFalse(self.bank.enabled)

    def test_rename_mode(self):
        self.cash.name = "Petty Cash"
        self.cash.save()
        self.cash.refresh_from_db()
        self.assertEqual(self.cash.name, "Petty Cash")

    def test_delete(self):
        pk = self.phone.pk
        self.phone.delete()
        self.assertFalse(ModeOfPayment.objects.filter(pk=pk).exists())

    def test_ordering_alphabetical(self):
        names = list(ModeOfPayment.objects.values_list("name", flat=True))
        self.assertEqual(names, sorted(names))

    def test_get_type_display(self):
        self.assertEqual(self.cash.get_type_display(), "Cash")
        self.assertEqual(self.bank.get_type_display(), "Bank")
        self.assertEqual(self.phone.get_type_display(), "Phone")


class ModeOfPaymentSeedMigrationTest(TestCase):
    """Verify the 0002 seed migration created the four default payment modes."""

    def test_seed_creates_defaults(self):
        # Migration has already run in test setup; just check the seed data exists.
        names = set(ModeOfPayment.objects.values_list("name", flat=True))
        self.assertIn("Cash", names)
        self.assertIn("Bank Transfer", names)
        self.assertIn("Card", names)
        self.assertIn("USSD / Mobile Money", names)

    def test_seed_types(self):
        self.assertEqual(ModeOfPayment.objects.get(name="Cash").type, "CASH")
        self.assertEqual(ModeOfPayment.objects.get(name="Bank Transfer").type, "BANK")
        self.assertEqual(ModeOfPayment.objects.get(name="Card").type, "BANK")
        self.assertEqual(ModeOfPayment.objects.get(name="USSD / Mobile Money").type, "PHONE")

    def test_seed_enabled(self):
        self.assertTrue(ModeOfPayment.objects.filter(enabled=True).count() >= 4)

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.payments.models import ModeOfPayment, PaymentGLMapping


class PaymentGLMappingModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cash = ModeOfPayment.objects.create(name="Test Cash", type="CASH")
        cls.bank = ModeOfPayment.objects.create(name="Test Bank", type="BANK")
        cls.mapping = PaymentGLMapping.objects.create(mode_of_payment=cls.cash, default_account="Cash in Hand - NGN")

    def test_str(self):
        self.assertEqual(str(self.mapping), "Test Cash → Cash in Hand - NGN")

    def test_mode_unique(self):
        with self.assertRaises(IntegrityError):
            PaymentGLMapping.objects.create(mode_of_payment=self.cash, default_account="Another Account")

    def test_different_modes_allowed(self):
        PaymentGLMapping.objects.create(mode_of_payment=self.bank, default_account="Bank Clearing")
        self.assertEqual(PaymentGLMapping.objects.count(), 2)

    def test_protect_on_mode_delete(self):
        """Deleting a mode that's referenced by a mapping should be blocked."""
        with self.assertRaises(IntegrityError):
            self.cash.delete()

    def test_clean_no_account_raises(self):
        m = PaymentGLMapping(mode_of_payment=self.bank, default_account="")
        with self.assertRaises(ValidationError) as ctx:
            m.full_clean()
        self.assertIn("default_account", ctx.exception.message_dict)

    def test_ordering(self):
        PaymentGLMapping.objects.create(mode_of_payment=self.bank, default_account="Bank")
        ordered = list(PaymentGLMapping.objects.values_list("mode_of_payment__name", flat=True))
        self.assertEqual(ordered, sorted(ordered))

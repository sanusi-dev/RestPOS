from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.payments.models import ModeOfPayment, PaymentGLMapping

from .helpers import create_payment_accounts


class PaymentGLMappingModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.accounts = create_payment_accounts()
        cls.cash = ModeOfPayment.objects.create(name="Test Cash", type="CASH")
        cls.bank = ModeOfPayment.objects.create(name="Test Bank", type="BANK")
        cls.mapping = PaymentGLMapping.objects.create(mode_of_payment=cls.cash, default_account=cls.accounts["cash"])

    def test_clean_no_account_raises(self):
        m = PaymentGLMapping(mode_of_payment=self.bank)
        with self.assertRaises(ValidationError) as ctx:
            m.full_clean()
        self.assertIn("default_account", ctx.exception.message_dict)

    def test_leaf_only_validation(self):
        with self.assertRaises(ValidationError):
            PaymentGLMapping(mode_of_payment=self.bank, default_account=self.accounts["assets"]).full_clean()

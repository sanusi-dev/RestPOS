from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import Branch, Restaurant, Room


class PaymentGLMappingModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Use unique test names that don't collide with the seed migration's defaults.
        cls.cash = ModeOfPayment.objects.create(name="Test Cash", type="CASH")
        cls.bank = ModeOfPayment.objects.create(name="Test Bank", type="BANK")
        cls.mapping = PaymentGLMapping.objects.create(
            mode_of_payment=cls.cash,
            company="Test Co",
            default_account="Cash in Hand - NGN",
        )

    def test_str(self):
        self.assertEqual(str(self.mapping), "Test Cash → Cash in Hand - NGN")

    def test_unique_mode_per_company(self):
        with self.assertRaises(IntegrityError):
            PaymentGLMapping.objects.create(
                mode_of_payment=self.cash,
                company="Test Co",
                default_account="Another Account",
            )

    def test_same_mode_different_companies_allowed(self):
        m = PaymentGLMapping.objects.create(
            mode_of_payment=self.cash,
            company="Other Co",
            default_account="Cash in Hand",
        )
        self.assertEqual(m.pk, m.pk)
        self.assertEqual(PaymentGLMapping.objects.filter(mode_of_payment=self.cash).count(), 2)

    def test_different_modes_same_company_allowed(self):
        PaymentGLMapping.objects.create(
            mode_of_payment=self.bank,
            company="Test Co",
            default_account="Bank Clearing",
        )
        self.assertEqual(PaymentGLMapping.objects.filter(company="Test Co").count(), 2)

    def test_protect_on_mode_delete(self):
        """Deleting a mode that's referenced by a mapping should be blocked."""
        with self.assertRaises(IntegrityError):
            self.cash.delete()

    def test_save_defaults_company_from_restaurant(self):
        """save() auto-fills company from the Restaurant singleton when blank."""
        branch = Branch.objects.create(name="Main")
        room = Room.objects.create(branch=branch, name="Hall")
        restaurant = Restaurant.objects.create(
            company="Restaurant Default Co",
            branch=branch,
            default_room=room,
        )
        m = PaymentGLMapping(
            mode_of_payment=self.bank,
            default_account="Bank Account",
        )
        m.save()
        self.assertEqual(m.company, "Restaurant Default Co")
        restaurant.delete()

    def test_clean_no_account_raises(self):
        m = PaymentGLMapping(
            mode_of_payment=self.bank,
            company="Test Co",
            default_account="",
        )
        with self.assertRaises(ValidationError) as ctx:
            m.full_clean()
        self.assertIn("default_account", ctx.exception.message_dict)

    def test_ordering(self):
        PaymentGLMapping.objects.create(
            mode_of_payment=self.bank,
            company="Test Co",
            default_account="Bank",
        )
        ordered = list(PaymentGLMapping.objects.values_list("mode_of_payment__name", flat=True))
        self.assertEqual(ordered, sorted(ordered))

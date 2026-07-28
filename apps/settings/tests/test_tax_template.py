from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.settings.models import Branch, Restaurant, Room, TaxRate, TaxTemplate


class TaxTemplateModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.restaurant = Restaurant.objects.create(company="Test Co", branch=cls.branch, default_room=cls.room)
        cls.template = TaxTemplate.objects.create(title="Nigerian VAT", company="Test Co")

    def test_str_returns_title(self):
        self.assertEqual(str(self.template), "Nigerian VAT")

    def test_is_default_false_by_default(self):
        self.assertFalse(self.template.is_default)

    def test_disabled_false_by_default(self):
        self.assertFalse(self.template.disabled)

    def test_unique_together_title_company(self):
        with self.assertRaises(IntegrityError):
            TaxTemplate.objects.create(title="Nigerian VAT", company="Test Co")

    def test_different_company_same_title_allowed(self):
        t2 = TaxTemplate.objects.create(title="Nigerian VAT", company="Other Co")
        self.assertIsNotNone(t2.pk)

    def test_disabled_and_default_raises(self):
        self.template.is_default = True
        self.template.disabled = True
        with self.assertRaises(ValidationError):
            self.template.clean()

    def test_default_exclusivity_per_company(self):
        t2 = TaxTemplate.objects.create(title="State Tax", company="Test Co", is_default=True)
        self.template.is_default = True
        self.template.clean()
        self.template.save()
        t2.refresh_from_db()
        self.assertFalse(t2.is_default)

    def test_tax_category_uniqueness_per_company(self):
        self.template.tax_category = "Standard"
        self.template.save()
        t2 = TaxTemplate(title="Other VAT", company="Test Co", tax_category="Standard")
        with self.assertRaises(ValidationError):
            t2.clean()

    def test_tax_category_same_for_different_company_ok(self):
        self.template.tax_category = "Standard"
        self.template.save()
        t2 = TaxTemplate(title="Other VAT", company="Other Co", tax_category="Standard")
        t2.clean()

    def test_delete(self):
        pk = self.template.pk
        self.template.delete()
        self.assertFalse(TaxTemplate.objects.filter(pk=pk).exists())

    def test_ordering_by_title(self):
        TaxTemplate.objects.create(title="AAA Tax", company="Test Co")
        first = TaxTemplate.objects.first()
        self.assertEqual(first.title, "AAA Tax")


class TaxRateModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.template = TaxTemplate.objects.create(title="VAT", company="Test Co")

    def test_create_tax_rate(self):
        rate = TaxRate.objects.create(
            tax_template=self.template,
            charge_type=TaxRate.ON_NET_TOTAL,
            rate=Decimal("7.5"),
            account_head="VAT Payable",
            description="7.5% VAT on net total",
        )
        self.assertIsNotNone(rate.pk)

    def test_default_charge_type(self):
        rate = TaxRate.objects.create(tax_template=self.template, account_head="VAT", description="VAT")
        self.assertEqual(rate.charge_type, TaxRate.ON_NET_TOTAL)

    def test_str_representation(self):
        rate = TaxRate.objects.create(
            tax_template=self.template,
            charge_type=TaxRate.ON_NET_TOTAL,
            rate=Decimal("7.5"),
            account_head="VAT Payable",
            description="VAT",
        )
        self.assertIn("7.5", str(rate))
        self.assertIn("VAT Payable", str(rate))

    def test_cascade_delete_on_template(self):
        rate = TaxRate.objects.create(tax_template=self.template, account_head="VAT", description="VAT")
        self.template.delete()
        self.assertFalse(TaxRate.objects.filter(pk=rate.pk).exists())

    def test_charge_type_choices(self):
        rate = TaxRate(
            tax_template=self.template,
            charge_type="INVALID",
            account_head="VAT",
            description="VAT",
        )
        with self.assertRaises(ValidationError):
            rate.full_clean()

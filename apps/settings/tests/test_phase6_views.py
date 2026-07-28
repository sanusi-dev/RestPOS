from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.inventory.models import Warehouse
from apps.payments.models import ModeOfPayment, PaymentGLMapping
from apps.settings.models import (
    Branch,
    POSProfile,
    POSProfilePayment,
    ProductionUnit,
    Restaurant,
    Room,
    TaxTemplate,
)
from apps.users.models import CustomUser


class Phase6ViewTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username="admin@test.com", password="testpass123", email="admin@test.com"
        )
        mgr, _ = Group.objects.get_or_create(name="RestPOS Manager")
        cls.user.groups.add(mgr)
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.restaurant = Restaurant.objects.create(company="Test Co", branch=cls.branch, default_room=cls.room)
        cls.warehouse = Warehouse.objects.create(name="Kitchen", branch=cls.branch)
        cls.cash = ModeOfPayment.objects.get(name="Cash")
        PaymentGLMapping.objects.create(mode_of_payment=cls.cash, company="Test Co", default_account="Cash Account")
        cls.profile = POSProfile.objects.create(name="Main Cashier", warehouse=cls.warehouse)
        POSProfilePayment.objects.create(pos_profile=cls.profile, mode_of_payment=cls.cash, is_default=True)
        cls.unit = ProductionUnit.objects.create(
            name="Kitchen", branch=cls.branch, warehouse=cls.warehouse, department="FOOD"
        )
        cls.tax_template = TaxTemplate.objects.create(title="VAT", company="Test Co")

    def setUp(self):
        self.client.login(username="admin@test.com", password="testpass123")


class TestLoginRequired(TestCase):
    def test_pos_profile_settings_requires_login(self):
        response = self.client.get(reverse("settings:pos_profile_settings"))
        self.assertEqual(response.status_code, 302)

    def test_production_unit_list_requires_login(self):
        response = self.client.get(reverse("settings:production_unit_list"))
        self.assertEqual(response.status_code, 302)

    def test_tax_template_list_requires_login(self):
        response = self.client.get(reverse("settings:tax_template_list"))
        self.assertEqual(response.status_code, 302)


class TestPOSProfileSettingsView(Phase6ViewTestBase):
    def test_get_200(self):
        response = self.client.get(reverse("settings:pos_profile_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Main Cashier")

    def test_get_200_no_profile(self):
        ProductionUnit.objects.all().delete()
        POSProfile.objects.all().delete()
        response = self.client.get(reverse("settings:pos_profile_settings"))
        self.assertEqual(response.status_code, 200)

    def test_post_creates_when_none(self):
        ProductionUnit.objects.all().delete()
        POSProfile.objects.all().delete()
        response = self.client.post(
            reverse("settings:pos_profile_settings"),
            {
                "name": "New Profile",
                "warehouse": self.warehouse.pk,
                "currency": "NGN",
                "apply_discount_on": "GRAND_TOTAL",
                "action_on_new_invoice": "ALWAYS_ASK",
                "write_off_limit": "1.00",
                "paid_limit": 20,
                "table_attention_time": 0,
                "kot_warning_time": 15,
                "kot_naming_series": "KOT-####",
            },
        )
        self.assertRedirects(response, reverse("settings:pos_profile_settings"))
        self.assertTrue(POSProfile.objects.filter(name="New Profile").exists())

    def test_post_updates_existing(self):
        response = self.client.post(
            reverse("settings:pos_profile_settings"),
            {
                "name": "Updated Cashier",
                "warehouse": self.warehouse.pk,
                "currency": "NGN",
                "apply_discount_on": "GRAND_TOTAL",
                "action_on_new_invoice": "ALWAYS_ASK",
                "write_off_limit": "1.00",
                "paid_limit": 20,
                "table_attention_time": 0,
                "kot_warning_time": 15,
                "kot_naming_series": "KOT-####",
            },
        )
        self.assertRedirects(response, reverse("settings:pos_profile_settings"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.name, "Updated Cashier")


class TestProductionUnitViews(Phase6ViewTestBase):
    def test_list_200(self):
        response = self.client.get(reverse("settings:production_unit_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kitchen")

    def test_list_filter_by_department(self):
        ProductionUnit.objects.create(
            name="Bar Unit", branch=self.branch, warehouse=self.warehouse, department="DRINKS"
        )
        response = self.client.get(reverse("settings:production_unit_list"), {"department": "DRINKS"})
        self.assertContains(response, "Bar Unit")
        self.assertNotContains(response, ">Kitchen</a>")

    def test_create_get_200(self):
        response = self.client.get(reverse("settings:production_unit_create"))
        self.assertEqual(response.status_code, 200)

    def test_create_post(self):
        response = self.client.post(
            reverse("settings:production_unit_create"),
            {
                "name": "Bar",
                "department": "DRINKS",
                "warehouse": self.warehouse.pk,
                "printer_ip": "192.168.1.50",
                "printer_paper_width": "WIDTH_80MM",
                "printer_cut_mode": "FULL_CUT",
            },
        )
        self.assertRedirects(response, reverse("settings:production_unit_list"))
        self.assertTrue(ProductionUnit.objects.filter(name="Bar").exists())

    def test_detail_200(self):
        response = self.client.get(reverse("settings:production_unit_detail", kwargs={"pk": self.unit.pk}))
        self.assertEqual(response.status_code, 200)

    def test_update_get_200(self):
        response = self.client.get(reverse("settings:production_unit_update", kwargs={"pk": self.unit.pk}))
        self.assertEqual(response.status_code, 200)

    def test_delete_get_405(self):
        response = self.client.get(reverse("settings:production_unit_delete", kwargs={"pk": self.unit.pk}))
        self.assertEqual(response.status_code, 405)

    def test_delete_post(self):
        pk = self.unit.pk
        response = self.client.post(reverse("settings:production_unit_delete", kwargs={"pk": pk}))
        self.assertRedirects(response, reverse("settings:production_unit_list"))
        self.assertFalse(ProductionUnit.objects.filter(pk=pk).exists())


class TestTaxTemplateViews(Phase6ViewTestBase):
    def test_list_200(self):
        response = self.client.get(reverse("settings:tax_template_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "VAT")

    def test_create_get_200(self):
        response = self.client.get(reverse("settings:tax_template_create"))
        self.assertEqual(response.status_code, 200)

    def test_create_post(self):
        response = self.client.post(
            reverse("settings:tax_template_create"),
            {"title": "State Tax", "company": "Test Co"},
        )
        self.assertRedirects(response, reverse("settings:tax_template_list"))
        self.assertTrue(TaxTemplate.objects.filter(title="State Tax").exists())

    def test_detail_200(self):
        response = self.client.get(reverse("settings:tax_template_detail", kwargs={"pk": self.tax_template.pk}))
        self.assertEqual(response.status_code, 200)

    def test_update_get_200(self):
        response = self.client.get(reverse("settings:tax_template_update", kwargs={"pk": self.tax_template.pk}))
        self.assertEqual(response.status_code, 200)

    def test_delete_get_405(self):
        response = self.client.get(reverse("settings:tax_template_delete", kwargs={"pk": self.tax_template.pk}))
        self.assertEqual(response.status_code, 405)

    def test_delete_post(self):
        pk = self.tax_template.pk
        response = self.client.post(reverse("settings:tax_template_delete", kwargs={"pk": pk}))
        self.assertRedirects(response, reverse("settings:tax_template_list"))
        self.assertFalse(TaxTemplate.objects.filter(pk=pk).exists())


class TestManagerGuard(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.regular_user = CustomUser.objects.create_user(
            username="regular@test.com",
            password="testpass123",
            email="regular@test.com",
            is_staff=True,
        )
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.restaurant = Restaurant.objects.create(company="Test Co", branch=cls.branch, default_room=cls.room)
        cls.warehouse = Warehouse.objects.create(name="Kitchen", branch=cls.branch)
        cls.cash = ModeOfPayment.objects.get(name="Cash")
        PaymentGLMapping.objects.create(mode_of_payment=cls.cash, company="Test Co", default_account="Cash Account")
        cls.profile = POSProfile.objects.create(name="Main Cashier", warehouse=cls.warehouse)
        POSProfilePayment.objects.create(pos_profile=cls.profile, mode_of_payment=cls.cash, is_default=True)

    def setUp(self):
        self.client.login(username="regular@test.com", password="testpass123")

    def test_pos_profile_settings_get_ok(self):
        response = self.client.get(reverse("settings:pos_profile_settings"))
        self.assertEqual(response.status_code, 200)

    def test_pos_profile_settings_post_redirects_non_manager(self):
        response = self.client.post(reverse("settings:pos_profile_settings"), {"name": "X", "warehouse": 1})
        self.assertEqual(response.status_code, 302)

    def test_production_unit_create_redirects_non_manager(self):
        response = self.client.get(reverse("settings:production_unit_create"))
        self.assertEqual(response.status_code, 302)

    def test_tax_template_create_redirects_non_manager(self):
        response = self.client.get(reverse("settings:tax_template_create"))
        self.assertEqual(response.status_code, 302)

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.users.models import CustomUser


class DashboardContentTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        mgr, _ = Group.objects.get_or_create(name="RestPOS Manager")
        cls.user = CustomUser.objects.create_user(
            username="dashboard@test.com", password="testpass123", email="dashboard@test.com"
        )
        cls.user.groups.add(mgr)

    def setUp(self):
        self.client.login(username="dashboard@test.com", password="testpass123")


class TestDashboardRenders(DashboardContentTestBase):
    def test_dashboard_200(self):
        response = self.client.get(reverse("web:dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_shows_shortcuts_section(self):
        """Assert the 'Your Shortcuts' quick-action buttons are rendered."""
        response = self.client.get(reverse("web:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your Shortcuts")
        self.assertContains(response, "Open Shift")
        self.assertContains(response, "Menu Items")
        self.assertContains(response, "Items")
        self.assertContains(response, "Stock Ledger")

    def test_dashboard_shows_masters_and_setup_cards(self):
        """Assert the 'Masters & Setup' grid of grouped link cards is rendered."""
        response = self.client.get(reverse("web:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Masters &amp; Setup")
        # Each card heading
        for card_heading in ("Menu", "POS", "Inventory", "Setup"):
            self.assertContains(response, f">{card_heading}<")

    def test_dashboard_pos_card_links_to_shifts(self):
        """Assert the POS card exposes shift workflow links."""
        response = self.client.get(reverse("web:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Opening Entries")
        self.assertContains(response, "Closing Entries")
        self.assertContains(response, "Payment Modes")

    def test_dashboard_no_live_panels(self):
        """Assert no live operational panels on the home dashboard."""
        response = self.client.get(reverse("web:dashboard"))
        self.assertEqual(response.status_code, 200)
        # No 'Opened by' / 'Recent Closes' / 'Low Stock Alerts' headlines
        self.assertNotContains(response, "Opened by")
        self.assertNotContains(response, "Recent Closes")
        self.assertNotContains(response, "Low Stock Alerts")


class TestDashboardLoginRequired(TestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("web:dashboard"))
        self.assertEqual(response.status_code, 302)

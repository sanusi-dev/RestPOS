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
        self.assertContains(response, "Quick links")
        self.assertContains(response, "Frequently used")
        self.assertContains(response, "Open a shift")
        self.assertContains(response, "Receive stock")
        self.assertContains(response, "Prepare daily P&amp;L")
        self.assertContains(response, "New journal entry")

    def test_dashboard_shows_masters_and_setup_cards(self):
        """Assert the 'Masters & Setup' grid of grouped link cards is rendered."""
        response = self.client.get(reverse("web:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Modules &amp; setup")
        # Each card heading
        for card_heading in ("Orders", "Inventory", "Menu", "Accounting", "Reports", "POS &amp; shifts", "Settings"):
            self.assertContains(response, f">{card_heading}<")

    def test_dashboard_pos_card_links_to_shifts(self):
        """Assert the POS card exposes shift workflow links."""
        response = self.client.get(reverse("web:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Opening entries")
        self.assertContains(response, "Closing entries")
        self.assertContains(response, "Payment modes")

    def test_dashboard_no_live_panels(self):
        """Assert no live operational panels on the home dashboard."""
        response = self.client.get(reverse("web:dashboard"))
        self.assertEqual(response.status_code, 200)
        # The home dashboard remains a navigator, not an operational status board.
        self.assertNotContains(response, "Opened by")
        self.assertNotContains(response, "Recent Closes")
        self.assertNotContains(response, "Low Stock Alerts")


class TestDashboardLoginRequired(TestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("web:dashboard"))
        self.assertEqual(response.status_code, 302)

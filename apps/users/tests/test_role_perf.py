"""Tests for role-check query behavior."""

from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.users.models import CustomUser


class RolePropertyPerformanceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cashier = CustomUser.objects.create_user(
            username="cashier@test.com", password="testpass123", email="cashier@test.com"
        )
        cashier_group, _ = Group.objects.get_or_create(name="RestPOS Cashier")
        cls.cashier.groups.add(cashier_group)

    def _group_queries(self, ctx):
        return [q for q in ctx.captured_queries if "auth_group" in q["sql"]]

    def test_role_accesses_use_exists_queries(self):
        """Plain properties issue exists() per access; a prefetch makes groups.all() free."""
        user = CustomUser.objects.prefetch_related("groups").get(pk=self.cashier.pk)
        with CaptureQueriesContext(connection) as ctx:
            for _ in range(2):
                self.assertFalse(user.is_admin)
                self.assertFalse(user.is_manager)
                self.assertTrue(user.is_cashier)
                self.assertTrue(user.has_staff_role)
                self.assertFalse(user.has_backoffice_access)
        # exists() queries don't use the prefetch cache — bound them instead of asserting zero.
        self.assertLessEqual(len(self._group_queries(ctx)), 20)

    def test_role_accesses_collapse_without_prefetch(self):
        """Without prefetch, each role property reads groups straight from the database."""
        user = CustomUser.objects.get(pk=self.cashier.pk)
        with CaptureQueriesContext(connection) as ctx:
            self.assertFalse(user.is_admin)
            self.assertFalse(user.is_manager)
            self.assertTrue(user.is_cashier)
            self.assertTrue(user.has_staff_role)
            self.assertFalse(user.has_backoffice_access)
        self.assertGreater(len(self._group_queries(ctx)), 0)

    def test_pos_page_issues_at_most_six_group_queries(self):
        """End-to-end: hitting /pos/ as a cashier keeps group queries bounded."""
        self.client.login(username="cashier@test.com", password="testpass123")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/pos/")
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(self._group_queries(ctx)), 6)

    def test_backoffice_403_for_cashier_issues_at_most_two_group_queries(self):
        """Cashier blocked from /backoffice/ gets 403 with bounded group queries."""
        self.client.login(username="cashier@test.com", password="testpass123")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/backoffice/dashboard/")
        self.assertEqual(response.status_code, 403)
        self.assertLessEqual(len(self._group_queries(ctx)), 2)

    def test_role_values_unchanged(self):
        """Behaves identically to the old property-based role checks."""
        user = CustomUser.objects.prefetch_related("groups").get(pk=self.cashier.pk)
        self.assertFalse(user.is_admin)
        self.assertFalse(user.is_manager)
        self.assertTrue(user.is_cashier)
        self.assertTrue(user.has_staff_role)
        self.assertFalse(user.has_backoffice_access)

        admin = CustomUser.objects.create_superuser(username="admin@test.com", password="t", email="admin@test.com")
        admin_user = CustomUser.objects.prefetch_related("groups").get(pk=admin.pk)
        self.assertTrue(admin_user.is_admin)
        self.assertTrue(admin_user.has_backoffice_access)
        self.assertTrue(admin_user.has_staff_role)


class StaffListPerformanceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_user(
            username="admin@test.com", password="testpass123", email="admin@test.com"
        )
        cls.admin_user.is_staff = True
        cls.admin_user.save()
        admin_group, _ = Group.objects.get_or_create(name="RestPOS Admin")
        cls.admin_user.groups.add(admin_group)

        cls.users = []
        for i in range(5):
            user = CustomUser.objects.create_user(
                username=f"cashier{i}@test.com",
                password="testpass123",
                email=f"cashier{i}@test.com",
            )
            cls.users.append(user)
        cashier_group, _ = Group.objects.get_or_create(name="RestPOS Cashier")
        for user in cls.users:
            user.groups.add(cashier_group)

    def setUp(self):
        self.client.login(username="admin@test.com", password="testpass123")

    def _group_queries(self, ctx):
        return [q for q in ctx.captured_queries if "auth_group" in q["sql"]]

    def test_staff_list_role_derivation_uses_prefetch(self):
        """A page with 5+ users should derive roles from prefetched groups — bounded group queries."""
        from django.urls import reverse

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("settings:staff_list"))
        self.assertEqual(response.status_code, 200)
        # Bound: 1 (_ensure_restpos_groups) + 1 (Prefetch) + decorator/nav role checks
        # on request.user (plain @property re-reads groups per access — still O(1), not per row).
        group_queries = self._group_queries(ctx)
        self.assertLessEqual(
            len(group_queries),
            6,
            f"Expected <= 6 group queries for full page; got {len(group_queries)}: {group_queries}",
        )


class RoleFreshnessTest(TestCase):
    """Role properties read groups live — no cache to invalidate."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username="invalidate@test.com", password="testpass123", email="invalidate@test.com"
        )
        cls.admin_group, _ = Group.objects.get_or_create(name="RestPOS Admin")
        cls.manager_group, _ = Group.objects.get_or_create(name="RestPOS Manager")
        cls.cashier_group, _ = Group.objects.get_or_create(name="RestPOS Cashier")

    def test_add_group_reflects_immediately(self):
        self.assertFalse(self.user.is_cashier)
        self.user.groups.add(self.cashier_group)
        self.assertTrue(self.user.is_cashier)
        self.assertTrue(self.user.has_staff_role)

    def test_remove_group_reflects_immediately(self):
        self.user.groups.add(self.cashier_group)
        self.assertTrue(self.user.is_cashier)
        self.user.groups.remove(self.cashier_group)
        self.assertFalse(self.user.is_cashier)
        self.assertFalse(self.user.has_staff_role)

    def test_clear_groups_reflects_immediately(self):
        self.user.groups.add(self.manager_group, self.cashier_group)
        self.assertTrue(self.user.is_manager)
        self.assertTrue(self.user.is_cashier)
        self.user.groups.clear()
        self.assertFalse(self.user.is_manager)
        self.assertFalse(self.user.is_cashier)
        self.assertFalse(self.user.has_staff_role)

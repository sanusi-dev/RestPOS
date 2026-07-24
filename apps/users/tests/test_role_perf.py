"""Regression tests for the role-check query collapse (Phase 1 perf fix).

Before the fix, every access to ``CustomUser.is_admin`` / ``is_manager`` / ``is_cashier``
ran ``groups.filter(name=...).exists()`` — one query per access. A POS cashier page
checks roles from middleware + templates ~9 times, so each page issued ~9 group
membership queries.

After the fix:
- ``is_admin`` / ``is_manager`` / ``is_cashier`` are ``@cached_property``.
- They read from ``_restpos_group_names`` (also a ``cached_property``) which uses
  the prefetched ``groups`` relation when available and otherwise issues exactly
  one query per request.
- ``BackofficeAccessMiddleware`` prefetches ``request.user.groups`` once on
  ``/pos/*`` and ``/backoffice/*`` paths.

These tests pin that behaviour down so a future refactor cannot silently
re-introduce the N+1.
"""

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

    def test_role_accesses_collapse_with_prefetch(self):
        """With groups prefetched, repeated role checks issue zero additional group queries."""
        user = CustomUser.objects.prefetch_related("groups").get(pk=self.cashier.pk)
        with CaptureQueriesContext(connection) as ctx:
            for _ in range(2):
                self.assertFalse(user.is_admin)
                self.assertFalse(user.is_manager)
                self.assertTrue(user.is_cashier)
                self.assertTrue(user.has_staff_role)
                self.assertFalse(user.has_backoffice_access)
        self.assertEqual(self._group_queries(ctx), [])

    def test_role_accesses_collapse_without_prefetch(self):
        """Without prefetch, all role accesses combined issue exactly one group query."""
        user = CustomUser.objects.get(pk=self.cashier.pk)
        with CaptureQueriesContext(connection) as ctx:
            self.assertFalse(user.is_admin)
            self.assertFalse(user.is_manager)
            self.assertTrue(user.is_cashier)
            self.assertTrue(user.has_staff_role)
            self.assertFalse(user.has_backoffice_access)
        self.assertEqual(len(self._group_queries(ctx)), 1)

    def test_pos_page_issues_at_most_one_group_query(self):
        """End-to-end: hitting /pos/ as a cashier makes at most one auth_group query."""
        self.client.login(username="cashier@test.com", password="testpass123")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/pos/")
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(self._group_queries(ctx)), 1)

    def test_backoffice_redirect_for_cashier_issues_at_most_one_group_query(self):
        """Cashier blocked from /backoffice/ should also collapse role checks."""
        self.client.login(username="cashier@test.com", password="testpass123")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/backoffice/dashboard/")
        self.assertEqual(response.status_code, 302)
        self.assertLessEqual(len(self._group_queries(ctx)), 1)

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
        # max queries: 1 (_ensure_restpos_groups via filter) + 1 (Prefetch fetch)
        # We assert <= 2 to allow either a shared prefetch SQL or an edge cache hit.
        group_queries = self._group_queries(ctx)
        self.assertLessEqual(
            len(group_queries),
            2,
            f"Expected <= 2 group queries for full page; got {len(group_queries)}: {group_queries}",
        )


class RoleCacheInvalidationTest(TestCase):
    """Regression tests for ``clear_role_caches_on_group_change``.

    ``is_admin`` / ``is_manager`` / ``is_cashier`` are ``@cached_property`` reading from
    ``_restpos_group_names``. Without invalidation, mutating a user's groups via
    ``user.groups.add/remove/clear`` would leave the cached role values stale — e.g. a
    cashier just demoted would still pass ``has_staff_role``.

    The ``m2m_changed`` receiver pops the cache so the next access re-computes from the
    current group membership. These tests pin that behaviour.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username="invalidate@test.com", password="testpass123", email="invalidate@test.com"
        )
        cls.admin_group, _ = Group.objects.get_or_create(name="RestPOS Admin")
        cls.manager_group, _ = Group.objects.get_or_create(name="RestPOS Manager")
        cls.cashier_group, _ = Group.objects.get_or_create(name="RestPOS Cashier")

    def test_add_group_invalidates_cache(self):
        # Cache the "no role" state, then add a group, then re-check on the SAME instance.
        self.assertFalse(self.user.is_cashier)
        self.user.groups.add(self.cashier_group)
        # If invalidation didn't fire, this would still be False (stale cache).
        self.assertTrue(self.user.is_cashier)
        self.assertTrue(self.user.has_staff_role)

    def test_remove_group_invalidates_cache(self):
        self.user.groups.add(self.cashier_group)
        self.assertTrue(self.user.is_cashier)
        self.user.groups.remove(self.cashier_group)
        # If invalidation didn't fire, this would still be True (stale cache).
        self.assertFalse(self.user.is_cashier)
        self.assertFalse(self.user.has_staff_role)

    def test_clear_groups_invalidates_cache(self):
        self.user.groups.add(self.manager_group, self.cashier_group)
        self.assertTrue(self.user.is_manager)
        self.assertTrue(self.user.is_cashier)
        self.user.groups.clear()
        self.assertFalse(self.user.is_manager)
        self.assertFalse(self.user.is_cashier)
        self.assertFalse(self.user.has_staff_role)

    def test_unrelated_m2m_action_does_not_invalidate(self):
        # post_add / post_remove / post_clear are the only actions that should pop the cache;
        # pre_add etc. must not — otherwise adding a group would clear the cache then re-populate
        # from the still-unchanged DB state before the row is inserted.
        self.user.groups.add(self.cashier_group)
        self.assertTrue(self.user.is_cashier)
        # Adding an already-present group fires post_add with no membership change — should be a no-op.
        self.user.groups.add(self.cashier_group)
        self.assertTrue(self.user.is_cashier)

from django.contrib.auth.models import Group
from django.urls import reverse

from .base import TestLoginRequiredViewBase, TestViewBase


class TestLandingPage(TestViewBase):
    def test_landing_page_renders_for_unauthenticated(self):
        response = self.client.get(reverse("web:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign In")
        self.assertContains(response, "Get Started")


class TestRoleBasedRedirects(TestViewBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager_group, _ = Group.objects.get_or_create(name="RestPOS Manager")
        cls.cashier_group, _ = Group.objects.get_or_create(name="RestPOS Cashier")

    def _make_user(
        self, username="testuser", email="test@example.com", is_staff=False, is_superuser=False, groups=None
    ):
        from apps.users.models import CustomUser

        user = CustomUser.objects.create_user(username=username, email=email, password="testpass")
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.save()
        if groups:
            user.groups.set(groups)
        return user

    def _login_and_follow_redirect(self, user):
        self.client.login(username=user.username, password="testpass")
        response = self.client.get(reverse("web:home"))
        return response

    def test_manager_redirects_to_dashboard(self):
        user = self._make_user(username="test_manager", groups=[self.manager_group])
        response = self._login_and_follow_redirect(user)
        self.assertRedirects(response, reverse("web:dashboard"))

    def test_cashier_redirects_to_pos(self):
        user = self._make_user(username="test_cashier", groups=[self.cashier_group])
        response = self._login_and_follow_redirect(user)
        self.assertRedirects(response, reverse("web:pos_index"))

    def test_superuser_redirects_to_dashboard(self):
        user = self._make_user(username="test_superuser", is_superuser=True)
        response = self._login_and_follow_redirect(user)
        self.assertRedirects(response, reverse("web:dashboard"))

    def test_staff_redirects_to_dashboard(self):
        user = self._make_user(username="test_staff_user", is_staff=True)
        response = self._login_and_follow_redirect(user)
        self.assertRedirects(response, reverse("web:dashboard"))

    def test_user_with_both_roles_is_manager(self):
        user = self._make_user(username="test_both", groups=[self.manager_group, self.cashier_group])
        self.assertTrue(user.has_backoffice_access)
        response = self._login_and_follow_redirect(user)
        self.assertRedirects(response, reverse("web:dashboard"))

    def test_no_role_user_redirects_to_pending_approval(self):
        user = self._make_user(username="test_newbie")
        response = self._login_and_follow_redirect(user)
        self.assertRedirects(response, reverse("web:pending_approval"))


class TestPendingApprovalView(TestLoginRequiredViewBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user.groups.clear()
        cls.authenticated_client.login(username="testing@example.com", password="12345")

    def test_pending_approval_view(self):
        self._run_tests(reverse("web:pending_approval"))

    def test_pending_approval_contains_message(self):
        response = self.authenticated_client.get(reverse("web:pending_approval"))
        self.assertContains(response, "Pending Approval")

    def test_staff_user_redirected_away_from_pending(self):
        manager_group, _ = Group.objects.get_or_create(name="RestPOS Manager")
        self.user.groups.add(manager_group)
        response = self.authenticated_client.get(reverse("web:pending_approval"))
        self.assertEqual(response.status_code, 302)


class TestDashboardView(TestLoginRequiredViewBase):
    def test_dashboard_view(self):
        self._run_tests(reverse("web:dashboard"))


class TestPOSView(TestLoginRequiredViewBase):
    def test_pos_view(self):
        self._run_tests(reverse("web:pos_index"))

    def test_pos_contains_backoffice_link(self):
        self.user.is_staff = True
        self.user.save()
        response = self.authenticated_client.get(reverse("web:pos_index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Go to Backoffice")


class TestCustomUserProperties(TestViewBase):
    def test_is_manager(self):
        from apps.users.models import CustomUser

        Group.objects.get_or_create(name="RestPOS Manager")
        user = CustomUser.objects.create_user(username="mgr@example.com", email="mgr@example.com")
        self.assertFalse(user.is_manager)
        user.groups.add(Group.objects.get(name="RestPOS Manager"))
        self.assertTrue(user.is_manager)

    def test_is_cashier(self):
        from apps.users.models import CustomUser

        Group.objects.get_or_create(name="RestPOS Cashier")
        user = CustomUser.objects.create_user(username="cash@example.com", email="cash@example.com")
        self.assertFalse(user.is_cashier)
        user.groups.add(Group.objects.get(name="RestPOS Cashier"))
        self.assertTrue(user.is_cashier)

    def test_has_backoffice_access_superuser(self):
        from apps.users.models import CustomUser

        user = CustomUser.objects.create_superuser(username="su@example.com", email="su@example.com")
        self.assertTrue(user.has_backoffice_access)

    def test_has_backoffice_access_staff(self):
        from apps.users.models import CustomUser

        user = CustomUser.objects.create_user(username="staff2@example.com", email="staff2@example.com")
        user.is_staff = True
        user.save()
        self.assertTrue(user.has_backoffice_access)

    def test_has_backoffice_access_manager(self):
        from apps.users.models import CustomUser

        mgr, _ = Group.objects.get_or_create(name="RestPOS Manager")
        user = CustomUser.objects.create_user(username="mgr2@example.com", email="mgr2@example.com")
        user.groups.add(mgr)
        self.assertTrue(user.has_backoffice_access)

    def test_has_backoffice_access_cashier_only(self):
        from apps.users.models import CustomUser

        cashier, _ = Group.objects.get_or_create(name="RestPOS Cashier")
        user = CustomUser.objects.create_user(username="cash2@example.com", email="cash2@example.com")
        user.groups.add(cashier)
        self.assertFalse(user.has_backoffice_access)

    def test_has_backoffice_access_anonymous_user(self):
        from apps.users.models import CustomUser

        user = CustomUser.objects.create_user(username="nobody@example.com", email="nobody@example.com")
        self.assertFalse(user.has_backoffice_access)

    def test_has_staff_role_manager(self):
        from apps.users.models import CustomUser

        mgr, _ = Group.objects.get_or_create(name="RestPOS Manager")
        user = CustomUser.objects.create_user(username="staffmgr@example.com", email="staffmgr@example.com")
        user.groups.add(mgr)
        self.assertTrue(user.has_staff_role)

    def test_has_staff_role_cashier(self):
        from apps.users.models import CustomUser

        cashier, _ = Group.objects.get_or_create(name="RestPOS Cashier")
        user = CustomUser.objects.create_user(username="staffcash@example.com", email="staffcash@example.com")
        user.groups.add(cashier)
        self.assertTrue(user.has_staff_role)

    def test_has_staff_role_superuser(self):
        from apps.users.models import CustomUser

        user = CustomUser.objects.create_superuser(username="staffsu@example.com", email="staffsu@example.com")
        self.assertTrue(user.has_staff_role)

    def test_has_staff_role_no_role(self):
        from apps.users.models import CustomUser

        user = CustomUser.objects.create_user(username="norole@example.com", email="norole@example.com")
        self.assertFalse(user.has_staff_role)

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.settings.models import Branch, Restaurant, Room, Table, UserRoomAssignment
from apps.users.models import CustomUser


class SettingsViewTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username="admin@test.com", password="testpass123", email="admin@test.com"
        )
        mgr, _ = Group.objects.get_or_create(name="RestPOS Manager")
        cls.user.groups.add(mgr)
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.table = Table.objects.create(
            room=cls.room, branch=cls.branch, name="T1", no_of_seats=4, table_shape="RECTANGLE"
        )

    def setUp(self):
        self.client.login(username="admin@test.com", password="testpass123")


class TestLoginRequired(TestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("settings:dashboard"))
        self.assertRedirects(response, f"/accounts/login/?next={reverse('settings:dashboard')}")

    def test_branch_list_requires_login(self):
        response = self.client.get(reverse("settings:branch_list"))
        self.assertEqual(response.status_code, 302)

    def test_room_list_requires_login(self):
        response = self.client.get(reverse("settings:room_list"))
        self.assertEqual(response.status_code, 302)

    def test_table_list_requires_login(self):
        response = self.client.get(reverse("settings:table_list"))
        self.assertEqual(response.status_code, 302)

    def test_restaurant_detail_requires_login(self):
        response = self.client.get(reverse("settings:restaurant_detail"))
        self.assertEqual(response.status_code, 302)

    def test_user_room_list_requires_login(self):
        response = self.client.get(reverse("settings:user_room_list"))
        self.assertEqual(response.status_code, 302)


class TestDashboardView(SettingsViewTestBase):
    def test_dashboard_200(self):
        response = self.client.get(reverse("settings:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Settings")


class TestBranchViews(SettingsViewTestBase):
    def test_branch_list_200(self):
        response = self.client.get(reverse("settings:branch_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Main Branch")

    def test_branch_create_get(self):
        response = self.client.get(reverse("settings:branch_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create Branch")

    def test_branch_create_post(self):
        response = self.client.post(
            reverse("settings:branch_create"),
            {"name": "New Branch"},
        )
        self.assertRedirects(response, reverse("settings:branch_list"))
        self.assertTrue(Branch.objects.filter(name="New Branch").exists())

    def test_branch_detail_200(self):
        response = self.client.get(reverse("settings:branch_detail", kwargs={"pk": self.branch.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Main Branch")

    def test_branch_detail_404(self):
        response = self.client.get(reverse("settings:branch_detail", kwargs={"pk": 9999}))
        self.assertEqual(response.status_code, 404)

    def test_branch_update_get(self):
        response = self.client.get(reverse("settings:branch_update", kwargs={"pk": self.branch.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit Branch")

    def test_branch_update_post(self):
        response = self.client.post(
            reverse("settings:branch_update", kwargs={"pk": self.branch.pk}),
            {"name": "Updated Branch"},
        )
        self.assertRedirects(response, reverse("settings:branch_detail", kwargs={"pk": self.branch.pk}))
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.name, "Updated Branch")


class TestRoomViews(SettingsViewTestBase):
    def test_room_list_200(self):
        response = self.client.get(reverse("settings:room_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hall")

    def test_room_create_get(self):
        response = self.client.get(reverse("settings:room_create"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="branch"')

    def test_room_create_post(self):
        response = self.client.post(
            reverse("settings:room_create"),
            {"name": "Garden"},
        )
        self.assertRedirects(response, reverse("settings:room_list"))
        room = Room.objects.get(name="Garden")
        self.assertEqual(room.branch_id, self.branch.pk)

    def test_room_detail_200(self):
        response = self.client.get(reverse("settings:room_detail", kwargs={"pk": self.room.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hall")

    def test_room_update_get(self):
        response = self.client.get(reverse("settings:room_update", kwargs={"pk": self.room.pk}))
        self.assertEqual(response.status_code, 200)

    def test_room_update_post(self):
        response = self.client.post(
            reverse("settings:room_update", kwargs={"pk": self.room.pk}),
            {"name": "Main Hall"},
        )
        self.assertRedirects(response, reverse("settings:room_detail", kwargs={"pk": self.room.pk}))
        self.room.refresh_from_db()
        self.assertEqual(self.room.name, "Main Hall")
        self.assertEqual(self.room.branch_id, self.branch.pk)


class TestTableViews(SettingsViewTestBase):
    def test_table_list_200(self):
        response = self.client.get(reverse("settings:table_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "T1")

    def test_table_list_filter_by_room(self):
        response = self.client.get(reverse("settings:table_list"), {"room": str(self.room.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "T1")

    def test_table_layout_200(self):
        response = self.client.get(reverse("settings:table_layout"))
        self.assertEqual(response.status_code, 200)

    def test_table_create_get(self):
        response = self.client.get(reverse("settings:table_create"))
        self.assertEqual(response.status_code, 200)

    def test_table_create_post(self):
        response = self.client.post(
            reverse("settings:table_create"),
            {
                "room": self.room.pk,
                "name": "T2",
                "no_of_seats": "2",
                "minimum_seating": "",
                "table_shape": "SQUARE",
                "is_take_away": "",
            },
        )
        self.assertRedirects(response, reverse("settings:table_list"))
        table = Table.objects.get(name="T2")
        self.assertEqual(table.branch_id, self.room.branch_id)

    def test_table_detail_200(self):
        response = self.client.get(reverse("settings:table_detail", kwargs={"pk": self.table.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "T1")

    def test_table_update_get(self):
        response = self.client.get(reverse("settings:table_update", kwargs={"pk": self.table.pk}))
        self.assertEqual(response.status_code, 200)

    def test_table_update_layout_post(self):
        response = self.client.post(
            reverse("settings:table_update_layout", kwargs={"pk": self.table.pk}),
            {"x": "10.5", "y": "20.0", "width": "120", "height": "80"},
        )
        self.assertEqual(response.status_code, 200)
        self.table.refresh_from_db()
        self.assertEqual(self.table.layout_x, 10.5)
        self.assertEqual(self.table.layout_y, 20.0)

    def test_table_update_layout_invalid(self):
        response = self.client.post(
            reverse("settings:table_update_layout", kwargs={"pk": self.table.pk}),
            {"x": "abc", "y": "20", "width": "120", "height": "80"},
        )
        self.assertEqual(response.status_code, 400)

    def test_table_update_layout_requires_post(self):
        response = self.client.get(reverse("settings:table_update_layout", kwargs={"pk": self.table.pk}))
        self.assertEqual(response.status_code, 405)


class TestRestaurantViews(SettingsViewTestBase):
    def test_restaurant_detail_no_config(self):
        Restaurant.objects.all().delete()
        response = self.client.get(reverse("settings:restaurant_detail"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No restaurant configuration")

    def test_restaurant_detail_with_config(self):
        Restaurant.objects.create(company="Test Co", branch=self.branch, default_room=self.room)
        response = self.client.get(reverse("settings:restaurant_detail"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Co")

    def test_restaurant_update_redirects_when_no_config(self):
        Restaurant.objects.all().delete()
        response = self.client.get(reverse("settings:restaurant_update"))
        self.assertRedirects(response, reverse("settings:restaurant_detail"))

    def test_restaurant_update_get(self):
        Restaurant.objects.create(company="Test Co", branch=self.branch, default_room=self.room)
        response = self.client.get(reverse("settings:restaurant_update"))
        self.assertEqual(response.status_code, 200)

    def test_restaurant_update_post(self):
        Restaurant.objects.create(company="Test Co", branch=self.branch, default_room=self.room)
        response = self.client.post(
            reverse("settings:restaurant_update"),
            {
                "company": "Updated Co",
                "invoice_series_prefix": "REST-",
                "address": "123 Street",
                "default_room": self.room.pk,
            },
        )
        self.assertRedirects(response, reverse("settings:restaurant_detail"))
        r = Restaurant.objects.get(branch=self.branch)
        self.assertEqual(r.company, "Updated Co")


class TestUserRoomAssignmentViews(SettingsViewTestBase):
    def test_user_room_list_200(self):
        UserRoomAssignment.objects.create(user=self.user, room=self.room, branch=self.branch)
        response = self.client.get(reverse("settings:user_room_list"))
        self.assertEqual(response.status_code, 200)

    def test_user_room_create_get(self):
        response = self.client.get(reverse("settings:user_room_create"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="branch"')

    def test_user_room_create_post(self):
        response = self.client.post(
            reverse("settings:user_room_create"),
            {"user": self.user.pk, "room": self.room.pk},
        )
        self.assertRedirects(response, reverse("settings:user_room_list"))
        assignment = UserRoomAssignment.objects.get(user=self.user, room=self.room)
        self.assertEqual(assignment.branch_id, self.room.branch_id)

    def test_user_room_update_get(self):
        a = UserRoomAssignment.objects.create(user=self.user, room=self.room, branch=self.branch)
        response = self.client.get(reverse("settings:user_room_update", kwargs={"pk": a.pk}))
        self.assertEqual(response.status_code, 200)

    def test_user_room_delete_post(self):
        a = UserRoomAssignment.objects.create(user=self.user, room=self.room, branch=self.branch)
        response = self.client.post(reverse("settings:user_room_delete", kwargs={"pk": a.pk}))
        self.assertRedirects(response, reverse("settings:user_room_list"))
        self.assertFalse(UserRoomAssignment.objects.filter(pk=a.pk).exists())

    def test_user_room_delete_requires_post(self):
        a = UserRoomAssignment.objects.create(user=self.user, room=self.room, branch=self.branch)
        response = self.client.get(reverse("settings:user_room_delete", kwargs={"pk": a.pk}))
        self.assertEqual(response.status_code, 405)


class TestStaffManagementViews(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_superuser(
            username="admin@test.com", password="testpass123", email="admin@test.com"
        )
        cls.manager_user = CustomUser.objects.create_user(
            username="manager@test.com", password="testpass123", email="manager@test.com"
        )
        cls.cashier = CustomUser.objects.create_user(
            username="cashier@test.com", password="testpass123", email="cashier@test.com"
        )
        cls.newbie = CustomUser.objects.create_user(
            username="newbie@test.com", password="testpass123", email="newbie@test.com"
        )
        from django.contrib.auth.models import Group

        cls.admin_group, _ = Group.objects.get_or_create(name="RestPOS Admin")
        cls.manager_group, _ = Group.objects.get_or_create(name="RestPOS Manager")
        cls.cashier_group, _ = Group.objects.get_or_create(name="RestPOS Cashier")
        cls.manager_user.groups.add(cls.manager_group)

    def setUp(self):
        self.client.login(username="admin@test.com", password="testpass123")

    def test_staff_list_200(self):
        response = self.client.get(reverse("settings:staff_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff Management")

    def test_staff_list_shows_users(self):
        response = self.client.get(reverse("settings:staff_list"))
        self.assertContains(response, "cashier@test.com")
        self.assertContains(response, "newbie@test.com")

    def test_staff_list_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("settings:staff_list"))
        self.assertEqual(response.status_code, 302)

    def test_staff_list_requires_backoffice_access(self):
        self.client.logout()
        self.client.login(username="newbie@test.com", password="testpass123")
        response = self.client.get(reverse("settings:staff_list"))
        self.assertEqual(response.status_code, 302)

    def test_assign_cashier_role(self):
        response = self.client.post(
            reverse("settings:staff_assign_role", kwargs={"pk": self.newbie.pk, "role": "cashier"})
        )
        self.assertRedirects(response, reverse("settings:staff_list"))
        self.assertTrue(self.newbie.groups.filter(name="RestPOS Cashier").exists())

    def test_assign_manager_role(self):
        response = self.client.post(
            reverse("settings:staff_assign_role", kwargs={"pk": self.cashier.pk, "role": "manager"})
        )
        self.assertRedirects(response, reverse("settings:staff_list"))
        self.assertTrue(self.cashier.groups.filter(name="RestPOS Manager").exists())

    def test_assign_admin_role(self):
        response = self.client.post(
            reverse("settings:staff_assign_role", kwargs={"pk": self.newbie.pk, "role": "admin"})
        )
        self.assertRedirects(response, reverse("settings:staff_list"))
        self.newbie.refresh_from_db()
        self.assertTrue(self.newbie.groups.filter(name="RestPOS Admin").exists())
        self.assertTrue(self.newbie.is_superuser)
        self.assertTrue(self.newbie.is_staff)

    def test_remove_role(self):
        self.cashier.groups.add(self.cashier_group)
        response = self.client.post(reverse("settings:staff_remove_role", kwargs={"pk": self.cashier.pk}))
        self.assertRedirects(response, reverse("settings:staff_list"))
        self.assertFalse(self.cashier.groups.filter(name="RestPOS Cashier").exists())

    def test_cannot_remove_admin(self):
        self.admin_user.groups.add(self.admin_group)
        response = self.client.post(reverse("settings:staff_remove_role", kwargs={"pk": self.admin_user.pk}))
        self.assertRedirects(response, reverse("settings:staff_list"))
        self.assertTrue(self.admin_user.groups.filter(name="RestPOS Admin").exists())

    def test_non_superuser_cannot_assign(self):
        self.client.logout()
        self.client.login(username="manager@test.com", password="testpass123")
        response = self.client.post(
            reverse("settings:staff_assign_role", kwargs={"pk": self.newbie.pk, "role": "cashier"})
        )
        self.assertEqual(response.status_code, 403)

    def test_non_superuser_cannot_remove(self):
        self.cashier.groups.add(self.cashier_group)
        self.client.logout()
        self.client.login(username="manager@test.com", password="testpass123")
        response = self.client.post(reverse("settings:staff_remove_role", kwargs={"pk": self.cashier.pk}))
        self.assertEqual(response.status_code, 403)

    def test_staff_list_search(self):
        response = self.client.get(reverse("settings:staff_list"), {"search": "cashier"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cashier@test.com")
        self.assertNotContains(response, "newbie@test.com")

    def test_staff_list_pagination(self):
        for i in range(25):
            CustomUser.objects.create_user(
                username=f"batch{i}@test.com", email=f"batch{i}@test.com", password="testpass123"
            )
        response = self.client.get(reverse("settings:staff_list"), {"page": 2})
        self.assertEqual(response.status_code, 200)

    def test_assign_role_requires_post(self):
        response = self.client.get(
            reverse("settings:staff_assign_role", kwargs={"pk": self.newbie.pk, "role": "cashier"})
        )
        self.assertEqual(response.status_code, 405)

    def test_remove_role_requires_post(self):
        response = self.client.get(reverse("settings:staff_remove_role", kwargs={"pk": self.cashier.pk}))
        self.assertEqual(response.status_code, 405)

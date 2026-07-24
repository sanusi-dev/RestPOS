from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.settings.models import Branch, Restaurant, Room


class RestaurantModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.restaurant = Restaurant.objects.create(
            company="Test Restaurant Ltd",
            branch=cls.branch,
            default_room=cls.room,
        )

    def test_str_returns_company(self):
        self.assertEqual(str(self.restaurant), "Test Restaurant Ltd")

    def test_str_falls_back_to_branch_name(self):
        r = Restaurant(company="", branch=self.branch, default_room=self.room)
        self.assertEqual(str(r), "Main Branch")

    def test_invoice_series_prefix_default(self):
        self.assertEqual(self.restaurant.invoice_series_prefix, "REST-")

    def test_singleton_per_branch_validation(self):
        r2 = Restaurant(company="Other", branch=self.branch, default_room=self.room)
        with self.assertRaises(ValidationError):
            r2.clean()

    def test_singleton_allows_update_of_same_record(self):
        self.restaurant.company = "Updated"
        self.restaurant.clean()

    def test_default_room_must_belong_to_same_branch(self):
        other_branch = Branch.objects.create(name="Other Branch")
        r2 = Restaurant(company="Other", branch=other_branch, default_room=self.room)
        with self.assertRaises(ValidationError):
            r2.clean()

    def test_multiple_branches_can_have_restaurant(self):
        other_branch = Branch.objects.create(name="Branch 2")
        other_room = Room.objects.create(branch=other_branch, name="Room 2")
        r2 = Restaurant.objects.create(company="Branch 2 Resto", branch=other_branch, default_room=other_room)
        r2.clean()

    def test_update(self):
        self.restaurant.company = "New Name"
        self.restaurant.save()
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.company, "New Name")

    def test_delete(self):
        pk = self.restaurant.pk
        self.restaurant.delete()
        self.assertFalse(Restaurant.objects.filter(pk=pk).exists())

    def test_ordering_by_company(self):
        first = Restaurant.objects.first()
        self.assertEqual(first, self.restaurant)

    def test_auto_assigns_default_branch(self):
        Restaurant.objects.all().delete()
        r = Restaurant.objects.create(company="Auto Branch Co", default_room=self.room)
        self.assertEqual(r.branch_id, self.branch.pk)

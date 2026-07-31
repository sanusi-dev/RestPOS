from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.settings.models import Restaurant


class RestaurantModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(company="Test Restaurant Ltd")

    def test_str_returns_company(self):
        self.assertEqual(str(self.restaurant), "Test Restaurant Ltd")

    def test_invoice_series_prefix_default(self):
        self.assertEqual(self.restaurant.invoice_series_prefix, "REST-")

    def test_singleton_rejects_second_record(self):
        r2 = Restaurant(company="Other")
        with self.assertRaises(ValidationError):
            r2.clean()

    def test_singleton_allows_update_of_same_record(self):
        self.restaurant.company = "Updated"
        self.restaurant.clean()

    def test_load_returns_the_singleton(self):
        self.assertEqual(Restaurant.load(), self.restaurant)

    def test_load_returns_none_when_empty(self):
        Restaurant.objects.all().delete()
        self.assertIsNone(Restaurant.load())

    def test_update(self):
        self.restaurant.company = "New Name"
        self.restaurant.save()
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.company, "New Name")

    def test_delete(self):
        pk = self.restaurant.pk
        self.restaurant.delete()
        self.assertFalse(Restaurant.objects.filter(pk=pk).exists())

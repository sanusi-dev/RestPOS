from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import Warehouse


class WarehouseModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.warehouse = Warehouse.objects.create(name="Main Store")

    def test_str_returns_name(self):
        self.assertEqual(str(self.warehouse), "Main Store")

    def test_defaults(self):
        self.assertFalse(self.warehouse.disabled)

    def test_name_unique(self):
        with self.assertRaises(IntegrityError):
            Warehouse.objects.create(name="Main Store")

    def test_disabled(self):
        self.warehouse.disabled = True
        self.warehouse.save()
        self.warehouse.refresh_from_db()
        self.assertTrue(self.warehouse.disabled)

    def test_delete(self):
        pk = self.warehouse.pk
        self.warehouse.delete()
        self.assertFalse(Warehouse.objects.filter(pk=pk).exists())

    def test_ordering(self):
        Warehouse.objects.create(name="Bar Store")
        whs = list(Warehouse.objects.values_list("name", flat=True))
        self.assertEqual(whs, ["Bar Store", "Main Store"])

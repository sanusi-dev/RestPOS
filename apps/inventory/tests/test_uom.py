from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import UOM


class UOMModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")

    def test_str_returns_name(self):
        self.assertEqual(str(self.uom), "Nos")

    def test_default_is_active(self):
        self.assertTrue(self.uom.is_active)

    def test_name_unique(self):
        with self.assertRaises(IntegrityError):
            UOM.objects.create(name="Nos")

    def test_create_inactive(self):
        uom = UOM.objects.create(name="Kg", is_active=False)
        self.assertFalse(uom.is_active)

    def test_toggle_active(self):
        self.uom.is_active = False
        self.uom.save()
        self.uom.refresh_from_db()
        self.assertFalse(self.uom.is_active)

    def test_update_name(self):
        self.uom.name = "Pieces"
        self.uom.save()
        self.uom.refresh_from_db()
        self.assertEqual(self.uom.name, "Pieces")

    def test_delete(self):
        pk = self.uom.pk
        self.uom.delete()
        self.assertFalse(UOM.objects.filter(pk=pk).exists())

    def test_ordering(self):
        UOM.objects.create(name="Box")
        UOM.objects.create(name="Litre")
        names = list(UOM.objects.values_list("name", flat=True))
        self.assertEqual(names, sorted(names))

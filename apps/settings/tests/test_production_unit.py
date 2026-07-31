from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import Warehouse
from apps.settings.models import ProductionUnit


class ProductionUnitModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.warehouse = Warehouse.objects.create(name="Kitchen")

    def _unit(self, name="Kitchen", department="FOOD", **kwargs):
        return ProductionUnit.objects.create(name=name, warehouse=self.warehouse, department=department, **kwargs)

    def test_str_returns_name(self):
        self.assertEqual(str(self._unit()), "Kitchen")

    def test_department_food(self):
        self.assertEqual(self._unit().department, "FOOD")

    def test_department_drinks(self):
        self.assertEqual(self._unit(name="Bar", department="DRINKS").department, "DRINKS")

    def test_block_takeaway_kot_default_false(self):
        self.assertFalse(self._unit().block_takeaway_kot)

    def test_printer_ip_blank_by_default(self):
        self.assertEqual(self._unit().printer_ip, "")

    def test_printer_paper_width_default_80mm(self):
        self.assertEqual(self._unit().printer_paper_width, "WIDTH_80MM")

    def test_printer_cut_mode_default_full_cut(self):
        self.assertEqual(self._unit().printer_cut_mode, "FULL_CUT")

    def test_name_unique(self):
        self._unit()
        with self.assertRaises(IntegrityError):
            self._unit()

    def test_delete(self):
        unit = self._unit()
        pk = unit.pk
        unit.delete()
        self.assertFalse(ProductionUnit.objects.filter(pk=pk).exists())

    def test_ordering_by_name(self):
        self._unit(name="Z Kitchen")
        self._unit(name="A Bar", department="DRINKS")
        first = ProductionUnit.objects.first()
        self.assertEqual(first.name, "A Bar")

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import Warehouse
from apps.settings.models import ProductionUnit, Restaurant


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

    def test_disabled_warehouse_rejected(self):
        self.warehouse.disabled = True
        self.warehouse.save()
        with self.assertRaises(ValidationError):
            ProductionUnit(name="Kitchen", warehouse=self.warehouse, department="FOOD").full_clean()

    def test_drinks_must_match_bar_and_food_must_differ_from_store_and_bar(self):
        store = Warehouse.objects.create(name="Store")
        bar = Warehouse.objects.create(name="Bar")
        Restaurant.objects.create(company="Test", store_warehouse=store, default_warehouse=bar)
        with self.assertRaises(ValidationError):
            ProductionUnit(name="Wrong Bar", warehouse=self.warehouse, department="DRINKS").full_clean()
        with self.assertRaises(ValidationError):
            ProductionUnit(name="Wrong Kitchen", warehouse=store, department="FOOD").full_clean()

    def test_configured_warehouse_cannot_be_disabled(self):
        unit = self._unit()
        self.warehouse.disabled = True
        with self.assertRaisesMessage(ValidationError, "configured production unit warehouse"):
            self.warehouse.full_clean()
        unit.delete()

    def test_restaurant_warehouses_cannot_be_disabled(self):
        store = Warehouse.objects.create(name="Store")
        bar = Warehouse.objects.create(name="Bar")
        Restaurant.objects.create(company="Test", store_warehouse=store, default_warehouse=bar)
        for warehouse in (store, bar):
            with self.subTest(warehouse=warehouse):
                warehouse.disabled = True
                with self.assertRaises(ValidationError):
                    warehouse.full_clean()

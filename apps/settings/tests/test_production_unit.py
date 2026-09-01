from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import Warehouse
from apps.settings.models import ProductionUnit, Restaurant


class ProductionUnitModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.warehouse = Warehouse.objects.create(name="Kitchen")

    def _unit(self, name="Kitchen", department="FOOD", **kwargs):
        return ProductionUnit.objects.create(name=name, warehouse=self.warehouse, department=department, **kwargs)

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

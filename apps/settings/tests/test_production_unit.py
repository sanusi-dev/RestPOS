from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import Warehouse
from apps.settings.models import (
    Branch,
    POSProfile,
    ProductionUnit,
    Restaurant,
    Room,
)


class ProductionUnitModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.restaurant = Restaurant.objects.create(company="Test Co", branch=cls.branch, default_room=cls.room)
        cls.warehouse = Warehouse.objects.create(name="Kitchen", branch=cls.branch)
        cls.profile = POSProfile.objects.create(name="Main Cashier", warehouse=cls.warehouse)

    def test_str_returns_name(self):
        unit = ProductionUnit.objects.create(
            name="Kitchen", branch=self.branch, warehouse=self.warehouse, department="FOOD"
        )
        self.assertEqual(str(unit), "Kitchen")

    def test_save_auto_assigns_branch_from_pos_profile(self):
        unit = ProductionUnit.objects.create(
            name="Kitchen",
            warehouse=self.warehouse,
            department="FOOD",
            pos_profile=self.profile,
        )
        self.assertEqual(unit.branch_id, self.branch.pk)

    def test_save_auto_assigns_branch_from_default(self):
        unit = ProductionUnit.objects.create(
            name="Kitchen",
            warehouse=self.warehouse,
            department="FOOD",
        )
        self.assertEqual(unit.branch_id, self.branch.pk)

    def test_save_auto_assigns_warehouse_from_pos_profile(self):
        unit = ProductionUnit.objects.create(
            name="Kitchen",
            department="FOOD",
            pos_profile=self.profile,
        )
        self.assertEqual(unit.warehouse_id, self.warehouse.pk)

    def test_department_food(self):
        unit = ProductionUnit.objects.create(
            name="Kitchen", branch=self.branch, warehouse=self.warehouse, department="FOOD"
        )
        self.assertEqual(unit.department, "FOOD")

    def test_department_drinks(self):
        unit = ProductionUnit.objects.create(
            name="Bar", branch=self.branch, warehouse=self.warehouse, department="DRINKS"
        )
        self.assertEqual(unit.department, "DRINKS")

    def test_block_takeaway_kot_default_false(self):
        unit = ProductionUnit.objects.create(
            name="Kitchen", branch=self.branch, warehouse=self.warehouse, department="FOOD"
        )
        self.assertFalse(unit.block_takeaway_kot)

    def test_printer_ip_blank_by_default(self):
        unit = ProductionUnit.objects.create(
            name="Kitchen", branch=self.branch, warehouse=self.warehouse, department="FOOD"
        )
        self.assertEqual(unit.printer_ip, "")

    def test_printer_paper_width_default_80mm(self):
        unit = ProductionUnit.objects.create(
            name="Kitchen", branch=self.branch, warehouse=self.warehouse, department="FOOD"
        )
        self.assertEqual(unit.printer_paper_width, "WIDTH_80MM")

    def test_printer_cut_mode_default_full_cut(self):
        unit = ProductionUnit.objects.create(
            name="Kitchen", branch=self.branch, warehouse=self.warehouse, department="FOOD"
        )
        self.assertEqual(unit.printer_cut_mode, "FULL_CUT")

    def test_unique_together_name_branch(self):
        ProductionUnit.objects.create(name="Kitchen", branch=self.branch, warehouse=self.warehouse, department="FOOD")
        with self.assertRaises(IntegrityError):
            ProductionUnit.objects.create(
                name="Kitchen", branch=self.branch, warehouse=self.warehouse, department="FOOD"
            )

    def test_clean_branch_mismatch_with_pos_profile(self):
        other_branch = Branch.objects.create(name="Other Branch")
        other_warehouse = Warehouse.objects.create(name="Other WH", branch=other_branch)
        other_profile = POSProfile.objects.create(name="Other Profile", warehouse=other_warehouse, branch=other_branch)
        unit = ProductionUnit(
            name="Unit",
            branch=self.branch,
            warehouse=self.warehouse,
            department="FOOD",
            pos_profile=other_profile,
        )
        with self.assertRaises(ValidationError):
            unit.clean()

    def test_delete(self):
        unit = ProductionUnit.objects.create(
            name="Kitchen", branch=self.branch, warehouse=self.warehouse, department="FOOD"
        )
        pk = unit.pk
        unit.delete()
        self.assertFalse(ProductionUnit.objects.filter(pk=pk).exists())

    def test_ordering_by_name(self):
        ProductionUnit.objects.create(name="Z Kitchen", branch=self.branch, warehouse=self.warehouse, department="FOOD")
        ProductionUnit.objects.create(name="A Bar", branch=self.branch, warehouse=self.warehouse, department="DRINKS")
        first = ProductionUnit.objects.first()
        self.assertEqual(first.name, "A Bar")

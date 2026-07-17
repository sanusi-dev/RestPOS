from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import Warehouse
from apps.settings.models import Branch


class WarehouseModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.warehouse = Warehouse.objects.create(name="Main Store", branch=cls.branch)

    def test_str_returns_name(self):
        self.assertEqual(str(self.warehouse), "Main Store")

    def test_defaults(self):
        self.assertFalse(self.warehouse.is_group)
        self.assertFalse(self.warehouse.is_rejected)
        self.assertFalse(self.warehouse.disabled)

    def test_branch_link(self):
        self.assertEqual(self.warehouse.branch, self.branch)
        self.assertIn(self.warehouse, self.branch.warehouses.all())

    def test_unique_together_name_branch(self):
        with self.assertRaises(IntegrityError):
            Warehouse.objects.create(name="Main Store", branch=self.branch)

    def test_same_name_different_branch(self):
        branch2 = Branch.objects.create(name="Branch 2")
        wh = Warehouse.objects.create(name="Main Store", branch=branch2)
        self.assertEqual(wh.name, "Main Store")

    def test_parent_child(self):
        child = Warehouse.objects.create(name="Kitchen Store", branch=self.branch, parent=self.warehouse)
        self.assertEqual(child.parent, self.warehouse)
        self.assertIn(child, self.warehouse.children.all())

    def test_is_group(self):
        self.warehouse.is_group = True
        self.warehouse.save()
        self.warehouse.refresh_from_db()
        self.assertTrue(self.warehouse.is_group)

    def test_disabled(self):
        self.warehouse.disabled = True
        self.warehouse.save()
        self.warehouse.refresh_from_db()
        self.assertTrue(self.warehouse.disabled)

    def test_is_rejected(self):
        self.warehouse.is_rejected = True
        self.warehouse.save()
        self.warehouse.refresh_from_db()
        self.assertTrue(self.warehouse.is_rejected)

    def test_delete(self):
        pk = self.warehouse.pk
        self.warehouse.delete()
        self.assertFalse(Warehouse.objects.filter(pk=pk).exists())

    def test_ordering(self):
        Warehouse.objects.create(name="Bar Store", branch=self.branch)
        whs = list(Warehouse.objects.values_list("name", flat=True))
        self.assertEqual(whs, ["Bar Store", "Main Store"])

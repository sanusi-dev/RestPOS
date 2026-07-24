from django.db.utils import IntegrityError
from django.test import TestCase

from apps.settings.models import Branch


class BranchModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")

    def test_str_returns_name(self):
        self.assertEqual(str(self.branch), "Main Branch")

    def test_name_unique(self):
        with self.assertRaises(IntegrityError):
            Branch.objects.create(name="Main Branch")

    def test_create(self):
        branch = Branch.objects.create(name="Branch 2")
        self.assertEqual(branch.name, "Branch 2")

    def test_update(self):
        self.branch.name = "Updated Branch"
        self.branch.save()
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.name, "Updated Branch")

    def test_delete(self):
        pk = self.branch.pk
        self.branch.delete()
        self.assertFalse(Branch.objects.filter(pk=pk).exists())

    def test_created_at_updated_at(self):
        self.assertIsNotNone(self.branch.created_at)
        self.assertIsNotNone(self.branch.updated_at)

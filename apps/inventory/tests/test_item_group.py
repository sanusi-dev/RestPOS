from django.test import TestCase

from apps.inventory.models import ItemGroup


class ItemGroupModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = ItemGroup.objects.create(name="Food", is_group=True)
        cls.child = ItemGroup.objects.create(name="Rice", parent=cls.root)

    def test_str_returns_name(self):
        self.assertEqual(str(self.root), "Food")
        self.assertEqual(str(self.child), "Rice")

    def test_default_is_group(self):
        self.assertFalse(self.child.is_group)

    def test_parent_child_relationship(self):
        self.assertEqual(self.child.parent, self.root)
        self.assertIn(self.child, self.root.children.all())

    def test_root_has_no_parent(self):
        self.assertIsNone(self.root.parent)

    def test_deep_tree(self):
        grandchild = ItemGroup.objects.create(name="Jollof", parent=self.child)
        self.assertEqual(grandchild.parent, self.child)
        self.assertIn(grandchild, self.child.children.all())

    def test_name_unique(self):
        from django.db.utils import IntegrityError

        with self.assertRaises(IntegrityError):
            ItemGroup.objects.create(name="Food")

    def test_update(self):
        self.child.description = "Rice dishes"
        self.child.save()
        self.child.refresh_from_db()
        self.assertEqual(self.child.description, "Rice dishes")

    def test_delete_child_does_not_delete_parent(self):
        pk = self.child.pk
        self.child.delete()
        self.assertTrue(ItemGroup.objects.filter(pk=self.root.pk).exists())
        self.assertFalse(ItemGroup.objects.filter(pk=pk).exists())

    def test_ordering(self):
        ItemGroup.objects.create(name="Beverages", is_group=True)
        names = list(ItemGroup.objects.values_list("name", flat=True))
        self.assertEqual(names, sorted(names))

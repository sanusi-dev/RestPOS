from django.test import TestCase

from apps.inventory.models import ItemGroup


class ItemGroupModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.group = ItemGroup.objects.create(name="Food")

    def test_str_returns_name(self):
        self.assertEqual(str(self.group), "Food")

    def test_name_unique(self):
        from django.db.utils import IntegrityError

        with self.assertRaises(IntegrityError):
            ItemGroup.objects.create(name="Food")

    def test_update(self):
        self.group.description = "All food items"
        self.group.save()
        self.group.refresh_from_db()
        self.assertEqual(self.group.description, "All food items")

    def test_ordering(self):
        ItemGroup.objects.create(name="Beverages")
        names = list(ItemGroup.objects.values_list("name", flat=True))
        self.assertEqual(names, sorted(names))

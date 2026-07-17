from decimal import Decimal

from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup, ProductBundle, ProductBundleItem


class ProductBundleModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.parent = Item.objects.create(
            item_code="COMBO01",
            item_name="Combo Meal",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_stock_item=False,
        )
        cls.component1 = Item.objects.create(
            item_code="RICE001",
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
        )
        cls.component2 = Item.objects.create(
            item_code="DRINK001",
            item_name="Coke",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="DRINKS",
        )
        cls.bundle = ProductBundle.objects.create(parent_item=cls.parent)

    def test_str_returns_parent_item_name(self):
        self.assertEqual(str(self.bundle), "Combo Meal")

    def test_default_is_active(self):
        self.assertTrue(self.bundle.is_active)

    def test_unique_parent_item(self):
        from django.db.utils import IntegrityError

        with self.assertRaises(IntegrityError):
            ProductBundle.objects.create(parent_item=self.parent)

    def test_create_bundle_item(self):
        item = ProductBundleItem.objects.create(bundle=self.bundle, item=self.component1, qty=Decimal("1"))
        self.assertEqual(str(item), "Jollof Rice x1")
        self.assertIn(item, self.bundle.items.all())

    def test_multiple_components(self):
        ProductBundleItem.objects.create(bundle=self.bundle, item=self.component1, qty=Decimal("1"))
        ProductBundleItem.objects.create(bundle=self.bundle, item=self.component2, qty=Decimal("2"))
        self.assertEqual(self.bundle.items.count(), 2)

    def test_update_bundle(self):
        self.bundle.is_active = False
        self.bundle.save()
        self.bundle.refresh_from_db()
        self.assertFalse(self.bundle.is_active)

    def test_delete_bundle_cascades_items(self):
        ProductBundleItem.objects.create(bundle=self.bundle, item=self.component1, qty=Decimal("1"))
        pk = self.bundle.pk
        self.bundle.delete()
        self.assertFalse(ProductBundle.objects.filter(pk=pk).exists())
        self.assertEqual(ProductBundleItem.objects.filter(bundle_id=pk).count(), 0)

    def test_delete_parent_item_cascades_bundle(self):
        pk = self.bundle.pk
        self.parent.delete()
        self.assertFalse(ProductBundle.objects.filter(pk=pk).exists())

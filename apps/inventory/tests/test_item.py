from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import (
    UOM,
    Item,
    ItemGroup,
    Warehouse,
)


class ItemTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.warehouse = Warehouse.objects.create(name="Main Store")
        cls.item = Item.objects.create(
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
        )


class ItemValidationTest(ItemTestBase):
    def test_has_variants_and_is_stock_item_raises(self):
        self.item.has_variants = True
        self.item.is_stock_item = True
        with self.assertRaises(ValidationError):
            self.item.full_clean()

    def test_template_cannot_be_sales_or_purchase(self):
        self.item.has_variants = True
        self.item.is_stock_item = False
        self.item.is_sales_item = True
        with self.assertRaises(ValidationError):
            self.item.full_clean()

    def test_variant_of_without_parent_has_variants_raises(self):
        parent = Item.objects.create(
            item_name="Template",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            has_variants=False,
            is_stock_item=False,
        )
        variant = Item(
            item_name="Variant",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            variant_of=parent,
        )
        with self.assertRaises(ValidationError):
            variant.full_clean()

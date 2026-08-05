from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.inventory.models import UOM, Item, ItemGroup


class BackfillItemImagesCommandTest(TestCase):
    def test_assigns_default_image_to_items_without_one(self):
        item = Item.objects.create(
            item_name="Jollof Rice",
            item_group=ItemGroup.objects.create(name="Food"),
            stock_uom=UOM.objects.create(name="Plate"),
            department="FOOD",
            image="",
        )

        call_command("backfill_item_images", stdout=StringIO())

        item.refresh_from_db()
        self.assertEqual(item.image.name, "items/default-item.png")

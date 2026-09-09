from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from apps.inventory.models import Item, ItemUOMConversion


class SeedMenuCatalogUOMTest(TestCase):
    def test_seed_drinks_per_bottle_with_crate_row(self):
        call_command("seed_menu_catalog", verbosity=0)
        coke = Item.objects.get(item_name="Coke (35cl)")
        self.assertEqual(coke.stock_uom.name, "Bottle")
        conv = ItemUOMConversion.objects.get(item=coke, uom__name="Crate")
        self.assertEqual(conv.conversion_factor, Decimal("24"))
        self.assertEqual(coke.last_purchase_rate, Decimal("200"))
        self.assertFalse(Item.objects.filter(item_name="Soft Drink Carton (24)").exists())
        self.assertFalse(Item.objects.filter(item_name="Beer Crate (Star)").exists())

    def test_seed_rice_per_kg_with_bag_row(self):
        call_command("seed_menu_catalog", verbosity=0)
        rice = Item.objects.get(item_name="Raw Rice (bag)")
        self.assertEqual(rice.stock_uom.name, "Kg")
        conv = ItemUOMConversion.objects.get(item=rice, uom__name="Bag")
        self.assertEqual(conv.conversion_factor, Decimal("50"))
        self.assertEqual(rice.last_purchase_rate, Decimal("900"))

    def test_seed_virtual_dishes_per_plate(self):
        call_command("seed_menu_catalog", verbosity=0)
        jollof = Item.objects.get(item_name="Jollof Rice")
        self.assertEqual(jollof.stock_uom.name, "Plate")
        self.assertFalse(jollof.uom_conversions.exists())
        self.assertFalse(jollof.is_stock_item)
        self.assertFalse(jollof.is_purchase_item)

    def test_seed_does_not_delete_existing_carton_sku(self):
        from apps.inventory.models import UOM, ItemGroup

        group = ItemGroup.objects.get_or_create(name="Supplies")[0]
        carton = UOM.objects.get_or_create(name="Carton")[0]
        Item.objects.create(
            item_name="Soft Drink Carton (24)",
            item_group=group,
            stock_uom=carton,
            department="DRINKS",
            is_stock_item=True,
            is_sales_item=True,
            is_purchase_item=True,
        )
        call_command("seed_menu_catalog", verbosity=0)
        self.assertTrue(Item.objects.filter(item_name="Soft Drink Carton (24)").exists())

    def test_force_updates_factor_and_last_purchase_rate(self):
        call_command("seed_menu_catalog", verbosity=0)
        coke = Item.objects.get(item_name="Coke (35cl)")
        conv = ItemUOMConversion.objects.get(item=coke, uom__name="Crate")
        conv.conversion_factor = Decimal("12")
        conv.save(update_fields=["conversion_factor", "updated_at"])
        coke.last_purchase_rate = Decimal("1")
        coke.save(update_fields=["last_purchase_rate", "updated_at"])
        call_command("seed_menu_catalog", "--force", verbosity=0)
        conv.refresh_from_db()
        coke.refresh_from_db()
        self.assertEqual(conv.conversion_factor, Decimal("24"))
        self.assertEqual(coke.last_purchase_rate, Decimal("200"))


class SeedRecipesTest(TestCase):
    def test_seed_creates_example_recipes_in_stock_uom(self):
        from apps.inventory.models import Recipe

        call_command("seed_menu_catalog", verbosity=0)
        jollof = Recipe.objects.get(item__item_name="Jollof Rice", is_active=True)
        self.assertEqual(jollof.output_qty, Decimal("1"))
        rice_row = jollof.items.get(ingredient__item_name="Raw Rice (bag)")
        self.assertEqual(rice_row.qty, Decimal("0.1250"))
        self.assertEqual(rice_row.ingredient.stock_uom.name, "Kg")
        self.assertTrue(Recipe.objects.filter(item__item_name="Egusi Soup", is_active=True).exists())
        self.assertTrue(Recipe.objects.filter(item__item_name="Quarter Chicken", is_active=True).exists())

    def test_seed_is_idempotent_and_force_updates_qty(self):
        from apps.inventory.models import Recipe

        call_command("seed_menu_catalog", verbosity=0)
        call_command("seed_menu_catalog", verbosity=0)
        self.assertEqual(Recipe.objects.filter(item__item_name="Jollof Rice", is_active=True).count(), 1)
        jollof = Recipe.objects.get(item__item_name="Jollof Rice", is_active=True)
        row = jollof.items.get(ingredient__item_name="Raw Rice (bag)")
        row.qty = Decimal("9")
        row.save(update_fields=["qty", "updated_at"])
        call_command("seed_menu_catalog", "--force", verbosity=0)
        row.refresh_from_db()
        self.assertEqual(row.qty, Decimal("0.1250"))

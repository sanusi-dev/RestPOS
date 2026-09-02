from django.db import migrations


def forwards(apps, schema_editor):
    Item = apps.get_model("inventory", "Item")

    # FOOD sellable (is_sales=True): virtual dishes — must be sales-only, !stock !purch
    Item.objects.filter(
        department="FOOD", is_sales_item=True, is_stock_item=True, has_variants=False
    ).update(is_stock_item=False)

    # FOOD sellable variants incorrectly seeded with stock before fix
    Item.objects.filter(
        variant_of__isnull=False, department="FOOD", is_sales_item=True
    ).update(is_stock_item=False, is_purchase_item=False)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0030_remove_item_safety_stock"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

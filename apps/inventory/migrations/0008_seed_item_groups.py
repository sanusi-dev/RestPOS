from django.db import migrations


def seed_base_data(apps, schema_editor):
    ItemGroup = apps.get_model("inventory", "ItemGroup")
    UOM = apps.get_model("inventory", "UOM")

    groups = [
        "Proteins",
        "Grains & Swallows",
        "Soups & Stews",
        "Sides",
        "Breakfast",
        "Small Chops & Snacks",
        "Soft Drinks",
        "Beer",
        "Spirits",
        "Wine",
        "Water",
        "Juice & Malt",
        "Supplies",
    ]
    for name in groups:
        ItemGroup.objects.get_or_create(name=name)

    uoms = [
        "Each",
        "Kg",
        "Gram",
        "Litre",
        "Millilitre",
        "Bag",
        "Mudu",
        "Derica",
        "Pack",
        "Carton",
        "Bottle",
        "Can",
        "Dozen",
        "Basin",
        "Paint Tin",
        "Crate",
        "Tray",
        "Sachet",
        "Box",
        "Roll",
    ]
    for name in uoms:
        UOM.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0007_remove_uom_is_active"),
    ]
    operations = [
        migrations.RunPython(seed_base_data, reverse_code=migrations.RunPython.noop),
    ]

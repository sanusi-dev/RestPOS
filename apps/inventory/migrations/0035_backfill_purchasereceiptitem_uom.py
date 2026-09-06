from django.db import migrations
from django.db.models import OuterRef, Subquery


def forwards(apps, schema_editor):
    PurchaseReceiptItem = apps.get_model("inventory", "PurchaseReceiptItem")
    Item = apps.get_model("inventory", "Item")
    PurchaseReceiptItem.objects.filter(uom_id__isnull=True).update(
        uom_id=Subquery(Item.objects.filter(pk=OuterRef("item_id")).values("stock_uom_id")[:1]),
        conversion_factor=1,
    )


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0034_itemuomconversion_and_receipt_uom"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

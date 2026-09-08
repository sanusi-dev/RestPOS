"""Backfill existing Material Receipt lines to the stock UOM (factor 1)."""

from django.db import migrations


def backfill_stock_entry_lines(apps, schema_editor):
    StockEntryDetail = apps.get_model("inventory", "StockEntryDetail")
    Item = apps.get_model("inventory", "Item")

    items = {i.pk: i for i in Item.objects.all()}
    for line in StockEntryDetail.objects.select_related("stock_entry", "item").filter(
        stock_entry__purpose="MATERIAL_RECEIPT", uom__isnull=True
    ):
        item = items.get(line.item_id)
        if item is None:
            continue
        line.uom_id = item.stock_uom_id
        line.conversion_factor = 1
        line.amount = (line.qty * line.basic_rate).quantize(2)
        line.save(update_fields=["uom_id", "conversion_factor", "amount"])


def unbackfill_stock_entry_lines(apps, schema_editor):
    StockEntryDetail = apps.get_model("inventory", "StockEntryDetail")
    StockEntryDetail.objects.filter(stock_entry__purpose="MATERIAL_RECEIPT").update(
        uom=None, conversion_factor=1, amount=0
    )


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0038_stockentrydetail_uom_fields"),
    ]

    operations = [
        migrations.RunPython(backfill_stock_entry_lines, unbackfill_stock_entry_lines),
    ]

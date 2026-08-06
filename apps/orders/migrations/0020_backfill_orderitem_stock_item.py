from django.db import migrations


def backfill_stock_item(apps, schema_editor):
    OrderItem = apps.get_model("orders", "OrderItem")
    for order_item in OrderItem.objects.select_related("item").filter(stock_item__isnull=True).iterator():
        OrderItem.objects.filter(pk=order_item.pk).update(stock_item=order_item.item.is_stock_item)


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0019_orderitem_stock_item_and_more"),
    ]

    operations = [migrations.RunPython(backfill_stock_item, migrations.RunPython.noop)]

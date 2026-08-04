from django.db import migrations


def backfill_department(apps, schema_editor):
    OrderItem = apps.get_model("orders", "OrderItem")
    for order_item in OrderItem.objects.select_related("item").filter(department__isnull=True).iterator():
        OrderItem.objects.filter(pk=order_item.pk).update(department=order_item.item.department)


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0017_orderauditevent_remove_orderitem_synced_and_more"),
    ]

    operations = [migrations.RunPython(backfill_department, migrations.RunPython.noop)]

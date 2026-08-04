from django.db import migrations


def reset_legacy_draft_reservations(apps, schema_editor):
    Bin = apps.get_model("inventory", "Bin")
    Order = apps.get_model("orders", "Order")

    Bin.objects.exclude(reserved_qty=0).update(reserved_qty=0)
    Order.objects.filter(status="DRAFT", is_return=False).update(stock_warehouse=None)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0024_alter_stockreconciliation_reason"),
        ("orders", "0021_kot_orders_kot_status_4fb02b_idx"),
        ("settings", "0024_restaurant_store_warehouse_and_more"),
    ]

    operations = [
        migrations.RunPython(reset_legacy_draft_reservations, migrations.RunPython.noop),
    ]

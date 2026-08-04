from django.db import migrations


def backfill_reason(apps, schema_editor):
    StockReconciliation = apps.get_model("inventory", "StockReconciliation")
    StockReconciliation.objects.filter(reason__isnull=True).update(reason="PHYSICAL_COUNT")


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0022_stockreconciliation_reason_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_reason, migrations.RunPython.noop),
    ]

from django.db import migrations


def delete_legacy_null_reason_rows(apps, schema_editor):
    """Drop development/dummy reconciliations that lack a required reason."""
    StockReconciliation = apps.get_model("inventory", "StockReconciliation")
    StockReconciliationItem = apps.get_model("inventory", "StockReconciliationItem")
    legacy = StockReconciliation.objects.filter(reason__isnull=True)
    StockReconciliationItem.objects.filter(reconciliation__in=legacy).delete()
    legacy.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0022_stockreconciliation_reason_and_more"),
    ]

    operations = [
        migrations.RunPython(delete_legacy_null_reason_rows, migrations.RunPython.noop),
    ]

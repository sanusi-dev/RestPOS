from django.db import migrations


def wipe_fifo_state(apps, schema_editor):
    StockLedgerEntry = apps.get_model("inventory", "StockLedgerEntry")
    Bin = apps.get_model("inventory", "Bin")
    StockLedgerEntry.objects.all().delete()
    Bin.objects.all().update(actual_qty=0, valuation_rate=0)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0028_remove_bin_stock_value_and_more"),
    ]

    operations = [
        migrations.RunPython(wipe_fifo_state, noop),
    ]

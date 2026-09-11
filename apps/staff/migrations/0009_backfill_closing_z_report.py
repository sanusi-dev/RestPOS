# Backfill bill_count and refunded_total for pre-migration SUBMITTED closings.

from decimal import Decimal

from django.db import migrations


def backfill_closing_sales(apps, schema_editor):
    POSClosingEntry = apps.get_model("staff", "POSClosingEntry")
    Order = apps.get_model("orders", "Order")
    for closing in POSClosingEntry.objects.filter(status="SUBMITTED").iterator():
        submitted = Order.objects.filter(
            opening_entry_id=closing.opening_entry_id,
            status="SUBMITTED",
            is_return=False,
            submitted_at__gte=closing.period_start_date,
            submitted_at__lte=closing.period_end_date,
        )
        bill_count = submitted.count()
        refunded = Order.objects.filter(
            opening_entry_id=closing.opening_entry_id,
            status="SUBMITTED",
            is_return=True,
            submitted_at__gte=closing.period_start_date,
            submitted_at__lte=closing.period_end_date,
        ).values_list("grand_total", flat=True)
        refunded_total = sum((abs(total or Decimal("0")) for total in refunded), Decimal("0"))
        POSClosingEntry.objects.filter(pk=closing.pk).update(
            bill_count=bill_count,
            refunded_total=refunded_total,
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("staff", "0008_posclosingentry_bill_count_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_closing_sales, noop),
    ]

from django.db import migrations


def normalize_cancel_reasons(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    valid_reasons = {"wrong_order", "customer_changed_mind", "cashier_error", "other"}

    for order in Order.objects.exclude(cancel_reason="").iterator():
        if order.cancel_reason in valid_reasons:
            continue
        order.cancel_reason_note = order.cancel_reason_note or order.cancel_reason
        order.cancel_reason = "other"
        order.save(update_fields=["cancel_reason", "cancel_reason_note"])


def backfill_ticket_type(apps, schema_editor):
    KOT = apps.get_model("orders", "KOT")
    ProductionUnit = apps.get_model("settings", "ProductionUnit")
    departments = dict(ProductionUnit.objects.values_list("pk", "department"))

    for kot in KOT.objects.all().iterator():
        kot.ticket_type = "kitchen" if departments.get(kot.production_unit_id) == "FOOD" else "bar"
        kot.save(update_fields=["ticket_type"])


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0014_kot_created_by_kot_print_status_kot_ticket_type_and_more"),
    ]

    operations = [
        migrations.RunPython(normalize_cancel_reasons, migrations.RunPython.noop),
        migrations.RunPython(backfill_ticket_type, migrations.RunPython.noop),
    ]

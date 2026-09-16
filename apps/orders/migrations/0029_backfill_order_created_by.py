from django.db import migrations


def backfill_created_by(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    OrderAuditEvent = apps.get_model("orders", "OrderAuditEvent")
    events = (
        OrderAuditEvent.objects.filter(
            order__created_by__isnull=True,
            event_type="CREATED",
            actor__isnull=False,
        )
        .order_by("order_id", "created_at", "pk")
        .values_list("order_id", "actor_id")
    )
    seen = set()
    for order_id, actor_id in events.iterator():
        if order_id in seen:
            continue
        seen.add(order_id)
        Order.objects.filter(pk=order_id, created_by__isnull=True).update(created_by_id=actor_id)


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0028_order_created_by"),
    ]

    operations = [
        migrations.RunPython(backfill_created_by, migrations.RunPython.noop),
    ]

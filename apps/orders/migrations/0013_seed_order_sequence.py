from django.db import migrations
from django.db.models import Max


def seed_sequence(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    OrderSequence = apps.get_model("orders", "OrderSequence")
    last = Order.objects.aggregate(max_num=Max("order_number"))["max_num"] or 0
    OrderSequence.objects.create(name="order", current_value=last)


def unseed_sequence(apps, schema_editor):
    OrderSequence = apps.get_model("orders", "OrderSequence")
    OrderSequence.objects.filter(name="order").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0012_ordersequence_alter_order_order_number"),
    ]

    operations = [
        migrations.RunPython(seed_sequence, unseed_sequence),
    ]

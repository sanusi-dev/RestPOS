"""Seed the four common payment modes for a Nigerian restaurant."""
from django.db import migrations


def seed_payment_modes(apps, schema_editor):
    ModeOfPayment = apps.get_model("payments", "ModeOfPayment")
    seed = [
        ("Cash", "CASH"),
        ("Bank Transfer", "BANK"),
        ("Card", "BANK"),
        ("USSD / Mobile Money", "PHONE"),
    ]
    for name, mode_type in seed:
        ModeOfPayment.objects.get_or_create(name=name, defaults={"type": mode_type})


def unseed_payment_modes(apps, schema_editor):
    ModeOfPayment = apps.get_model("payments", "ModeOfPayment")
    ModeOfPayment.objects.filter(
        name__in=["Cash", "Bank Transfer", "Card", "USSD / Mobile Money"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
    ]
    operations = [
        migrations.RunPython(seed_payment_modes, reverse_code=unseed_payment_modes),
    ]

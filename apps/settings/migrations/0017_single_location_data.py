"""Copy POSProfile configuration onto the Restaurant singleton and payment-mode defaults onto ModeOfPayment.

Aborts loudly if the database holds more than one Branch or POSProfile, or if dropping the
branch dimension would create duplicate Warehouse/Menu/ProductionUnit names.
"""

from django.db import migrations
from django.db.models import Count


def _assert_single_location(apps):
    Branch = apps.get_model("settings", "Branch")
    POSProfile = apps.get_model("settings", "POSProfile")
    if Branch.objects.count() > 1:
        raise RuntimeError(
            "Single-location cleanup: more than one Branch exists. Resolve branch data manually before migrating."
        )
    if POSProfile.objects.count() > 1:
        raise RuntimeError(
            "Single-location cleanup: more than one POSProfile exists. Resolve profile data manually before migrating."
        )
    for app_label, model_name in [("inventory", "Warehouse"), ("menu", "Menu"), ("settings", "ProductionUnit")]:
        model = apps.get_model(app_label, model_name)
        duplicates = model.objects.values("name").annotate(c=Count("id")).filter(c__gt=1)
        if duplicates.exists():
            names = ", ".join(d["name"] for d in duplicates)
            raise RuntimeError(
                f"Single-location cleanup: duplicate {model_name} names across branches ({names}). "
                "Rename them before migrating."
            )


def forwards(apps, schema_editor):
    _assert_single_location(apps)
    Restaurant = apps.get_model("settings", "Restaurant")
    POSProfile = apps.get_model("settings", "POSProfile")
    ModeOfPayment = apps.get_model("payments", "ModeOfPayment")

    restaurant = Restaurant.objects.order_by("pk").first()
    profile = POSProfile.objects.order_by("pk").first()
    if restaurant is not None and profile is not None:
        restaurant.default_warehouse_id = profile.warehouse_id
        restaurant.reset_order_number_daily = profile.reset_order_number_daily
        restaurant.currency = profile.currency or restaurant.currency
        restaurant.save(update_fields=["default_warehouse_id", "reset_order_number_daily", "currency"])

    if profile is not None:
        POSProfilePayment = apps.get_model("settings", "POSProfilePayment")
        link = POSProfilePayment.objects.filter(pos_profile=profile, is_default=True).first()
        if link is not None:
            ModeOfPayment.objects.filter(pk=link.mode_of_payment_id).update(is_default=True)


def backwards(apps, schema_editor):
    Restaurant = apps.get_model("settings", "Restaurant")
    POSProfile = apps.get_model("settings", "POSProfile")
    ModeOfPayment = apps.get_model("payments", "ModeOfPayment")

    restaurant = Restaurant.objects.order_by("pk").first()
    profile = POSProfile.objects.order_by("pk").first()
    if restaurant is not None and profile is not None:
        profile.warehouse_id = restaurant.default_warehouse_id
        profile.reset_order_number_daily = restaurant.reset_order_number_daily
        profile.currency = restaurant.currency
        profile.save(update_fields=["warehouse_id", "reset_order_number_daily", "currency"])

    default_mode = ModeOfPayment.objects.filter(is_default=True).first()
    if profile is not None and default_mode is not None:
        link_model = apps.get_model("settings", "POSProfilePayment")
        link_model.objects.filter(pos_profile=profile, mode_of_payment=default_mode).update(is_default=True)
        ModeOfPayment.objects.filter(pk=default_mode.pk).update(is_default=False)


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0020_remove_reconciliation_item_warehouse"),
        ("menu", "0004_alter_menu_options"),
        ("payments", "0003_alter_paymentglmapping_options_and_more"),
        ("settings", "0016_restaurant_currency_restaurant_default_warehouse_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

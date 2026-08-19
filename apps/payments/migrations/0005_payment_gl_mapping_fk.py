"""Convert PaymentGLMapping.default_account from a name string to a LedgerAccount FK.

Data migration: matches existing strings by name (case-insensitive), creating
a missing leaf account under Assets (Cash/Bank by mode type) when the string
does not match an existing account.
"""

import django.db.models.deletion
from django.db import migrations, models


def _create_missing_account(LedgerAccount, mode_of_payment):
    account_type = "Cash" if mode_of_payment.type == "CASH" else "Bank"
    assets_root = LedgerAccount.objects.filter(is_group=True, root_type="ASSET").first()
    if assets_root is None:
        assets_root = LedgerAccount.objects.create(
            name="Assets",
            is_group=True,
            root_type="ASSET",
            report_type="BALANCE_SHEET",
        )
    name = f"{mode_of_payment.name} Account"
    return LedgerAccount.objects.create(
        name=name,
        parent=assets_root,
        is_group=False,
        root_type="ASSET",
        report_type="BALANCE_SHEET",
        account_type=account_type,
    )


def forwards(apps, schema_editor):
    PaymentGLMapping = apps.get_model("payments", "PaymentGLMapping")
    LedgerAccount = apps.get_model("accounting", "LedgerAccount")

    for mapping in PaymentGLMapping.objects.select_related("mode_of_payment").all():
        raw = (mapping.default_account or "").strip()
        account = None
        if raw:
            account = LedgerAccount.objects.filter(name__iexact=raw).first()
        if account is None:
            account = _create_missing_account(LedgerAccount, mapping.mode_of_payment)
        mapping.default_account_new = account
        mapping.save(update_fields=["default_account_new"])

    # The rows above reference the new FK column whose constraint is deferred
    # during migrations; flush the pending checks before the next ALTER runs.
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def backwards(apps, schema_editor):
    PaymentGLMapping = apps.get_model("payments", "PaymentGLMapping")
    for mapping in PaymentGLMapping.objects.all():
        mapping.default_account = mapping.default_account_new.name if mapping.default_account_new else ""
        mapping.save(update_fields=["default_account"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0001_initial"),
        ("payments", "0004_modeofpayment_payments_one_default_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentglmapping",
            name="default_account_new",
            field=models.ForeignKey(
                help_text="Leaf ledger account debited/credited when this mode is used.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payment_gl_mappings",
                to="accounting.ledgeraccount",
                verbose_name="Default account",
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="paymentglmapping",
            name="default_account_new",
            field=models.ForeignKey(
                help_text="Leaf ledger account debited/credited when this mode is used.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payment_gl_mappings",
                to="accounting.ledgeraccount",
                verbose_name="Default account",
            ),
        ),
        migrations.RemoveField(
            model_name="paymentglmapping",
            name="default_account",
        ),
        migrations.RenameField(
            model_name="paymentglmapping",
            old_name="default_account_new",
            new_name="default_account",
        ),
    ]

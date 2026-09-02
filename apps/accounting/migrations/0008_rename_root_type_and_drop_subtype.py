"""Rename LedgerAccount.root_type to account_type and drop the sub-type field.

The old `account_type` field held sub-types (Cash/Bank/Stock/...) that no
business logic consumes — the five pillars in `root_type` are the only
classification. Rename preserves the pillar data; the sub-type column is
dropped. Hand-written because makemigrations would otherwise rename the
sub-type column into account_type and drop the pillar data.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0007_alter_supplier_payable_account"),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE accounting_ledgeraccount DROP COLUMN account_type",
            "ALTER TABLE accounting_ledgeraccount ADD COLUMN account_type varchar(30) NOT NULL DEFAULT ''",
        ),
        migrations.RenameField(
            model_name="ledgeraccount",
            old_name="root_type",
            new_name="account_type",
        ),
    ]

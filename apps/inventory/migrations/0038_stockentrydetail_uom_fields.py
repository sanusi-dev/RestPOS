# Generated content, trimmed to the StockEntryDetail UOM fields only.

from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0037_add_stock_entry_funding_account"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockentrydetail",
            name="amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), editable=False, max_digits=12),
        ),
        migrations.AddField(
            model_name="stockentrydetail",
            name="conversion_factor",
            field=models.DecimalField(decimal_places=4, default=Decimal("1"), max_digits=10),
        ),
        migrations.AddField(
            model_name="stockentrydetail",
            name="uom",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Unit the quantity is entered in — the stock unit or a bulk unit from the "
                    "item's conversion table."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="inventory.uom",
            ),
        ),
    ]

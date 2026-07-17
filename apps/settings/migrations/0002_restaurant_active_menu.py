from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("settings", "0001_initial"),
        ("menu", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="restaurant",
            name="active_menu",
            field=models.ForeignKey(
                "menu.Menu",
                on_delete=django.db.models.deletion.SET_NULL,
                null=True,
                blank=True,
                related_name="active_for_restaurants",
            ),
        ),
    ]

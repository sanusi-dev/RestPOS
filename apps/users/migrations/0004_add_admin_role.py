from django.db import migrations


def add_admin_role(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="RestPOS Admin")


def remove_admin_role(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="RestPOS Admin").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0003_create_roles"),
    ]
    operations = [
        migrations.RunPython(add_admin_role, reverse_code=remove_admin_role),
    ]

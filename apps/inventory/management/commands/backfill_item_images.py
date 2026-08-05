from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.inventory.models import Item


class Command(BaseCommand):
    help = "Assign the canonical default image to items without an image."

    def handle(self, *args, **options):
        default_name = "items/default-item.png"
        default_path = Path(settings.MEDIA_ROOT) / default_name
        if not default_path.is_file():
            raise CommandError(f"Default item image not found: {default_path}")

        updated = Item.objects.filter(Q(image="") | Q(image__isnull=True)).update(image=default_name)
        self.stdout.write(self.style.SUCCESS(f"Assigned the default image to {updated} item(s)."))

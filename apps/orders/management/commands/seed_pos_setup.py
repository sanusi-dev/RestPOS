"""Seed the app with realistic data for visual testing.

Creates the full configuration chain: TaxTemplate → Restaurant.default_tax_template
→ POSProfile → ProductionUnits → and sets up all cross-references so the POS
screen loads immediately.

Usage:
    make manage ARGS='seed_pos_setup'
    make manage ARGS='seed_pos_setup --force'
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Seed the restaurant with realistic POS configuration for visual testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recreate POSProfile/ProductionUnits/TaxTemplate even if they already exist.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.inventory.models import Warehouse
        from apps.payments.models import ModeOfPayment, PaymentGLMapping
        from apps.settings.models import (
            Branch,
            POSProfile,
            ProductionUnit,
            Restaurant,
            Room,
            Table,
            TaxRate,
            TaxTemplate,
        )

        force = options["force"]

        # ── Branch / Room / Restaurant (expect these to exist) ──
        branch = Branch.objects.order_by("pk").first()
        if branch is None:
            branch = Branch.objects.create(name="Main Branch")
            self.stdout.write(self.style.WARNING("Created default branch: Main Branch"))

        room = Room.objects.filter(branch=branch).first()
        if room is None:
            room = Room.objects.create(name="Main Hall", branch=branch)
            self.stdout.write(self.style.WARNING("Created room: Main Hall"))

        restaurant = Restaurant.objects.order_by("pk").first()
        if restaurant is None:
            restaurant = Restaurant.objects.create(company="Saki Restaurant", branch=branch, default_room=room)
            self.stdout.write(self.style.WARNING("Created restaurant: Saki Restaurant"))
        if restaurant.default_room_id != room.pk:
            restaurant.default_room = room
            restaurant.save(update_fields=["default_room"])

        # ── Warehouses ──
        bar = Warehouse.objects.filter(name="Bar", branch=branch).first()
        if bar is None:
            bar = Warehouse.objects.create(name="Bar", branch=branch)
        kitchen = Warehouse.objects.filter(name="Kitchen", branch=branch).first()
        if kitchen is None:
            kitchen = Warehouse.objects.create(name="Kitchen", branch=branch)
        store = Warehouse.objects.filter(name="Store", branch=branch).first()
        if store is None:
            store = Warehouse.objects.create(name="Store", branch=branch)

        # ── Tax Template ──
        vat, created = TaxTemplate.objects.get_or_create(
            title="Nigerian VAT 7.5%",
            company=restaurant.company,
            defaults={"is_default": True, "disabled": False, "tax_category": "Standard"},
        )
        if created:
            TaxRate.objects.create(
                tax_template=vat,
                charge_type="ON_NET_TOTAL",
                rate=Decimal("7.5"),
                account_head="VAT Payable",
                description="VAT 7.5% on net total",
            )
            self.stdout.write(self.style.SUCCESS("Created tax template: Nigerian VAT 7.5%"))
        elif force:
            vat.is_default = True
            vat.save()

        if restaurant.default_tax_template_id != vat.pk:
            restaurant.default_tax_template = vat
            restaurant.save(update_fields=["default_tax_template", "updated_at"])
            self.stdout.write(self.style.SUCCESS("Assigned default_tax_template to Restaurant"))

        # Ensure active_menu
        from apps.menu.models import Menu

        menu = Menu.objects.filter(branch=branch, enabled=True).first()
        if menu and restaurant.active_menu_id != menu.pk:
            restaurant.active_menu = menu
            restaurant.save(update_fields=["active_menu", "updated_at"])
            self.stdout.write(f"Active menu set: {menu.name}")

        # ── Tables (ensure we have some) ──
        table_names = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
        for tname in table_names:
            Table.objects.get_or_create(room=room, name=tname, defaults={"branch": branch})
        self.stdout.write(f"Ensured {Table.objects.filter(room=room).count()} tables in {room.name}")

        # ── Payment modes ──
        cash = ModeOfPayment.objects.filter(name="Cash").first()
        if cash is None:
            cash = ModeOfPayment.objects.create(name="Cash", type="CASH")
        electronic = ModeOfPayment.objects.filter(name="Electronic").first()
        if electronic is None:
            electronic = ModeOfPayment.objects.create(name="Electronic", type="BANK")
        for mode in [cash, electronic]:
            PaymentGLMapping.objects.get_or_create(
                mode_of_payment=mode,
                defaults={"default_account": f"{mode.name} Account"},
            )

        # ── POS Profile (singleton) ──
        profile = POSProfile.objects.first()
        if profile and force:
            profile.delete()
            profile = None
        if profile is None:
            profile = POSProfile.objects.create(
                name="Main Cashier",
                warehouse=bar,
                branch=branch,
                restaurant=restaurant,
            )
            self.stdout.write(self.style.SUCCESS("Created POS Profile: Main Cashier"))
        if profile.warehouse_id != bar.pk:
            profile.warehouse = bar
            profile.save(update_fields=["warehouse"])

        # Link payment modes
        from apps.settings.models import POSProfilePayment

        for mode in [cash, electronic]:
            POSProfilePayment.objects.get_or_create(
                pos_profile=profile,
                mode_of_payment=mode,
                defaults={"is_default": (mode == cash), "allow_in_returns": (mode == cash)},
            )
        self.stdout.write(f"Linked {profile.payment_links.count()} payment modes to POS Profile")

        # ── Production Units ──
        pu_kitchen, _ = ProductionUnit.objects.get_or_create(
            name="Kitchen",
            branch=branch,
            defaults={
                "department": "FOOD",
                "warehouse": kitchen,
                "printer_ip": "192.168.1.50",
                "printer_paper_width": "WIDTH_80MM",
                "printer_cut_mode": "FULL_CUT",
            },
        )
        pu_bar, _ = ProductionUnit.objects.get_or_create(
            name="Bar",
            branch=branch,
            defaults={
                "department": "DRINKS",
                "warehouse": bar,
                "printer_ip": "192.168.1.51",
                "printer_paper_width": "WIDTH_80MM",
                "printer_cut_mode": "FULL_CUT",
            },
        )
        # Auto-assign pos_profile
        for pu in [pu_kitchen, pu_bar]:
            if not pu.pos_profile_id:
                pu.save()  # triggers auto-assign in save()
        self.stdout.write(self.style.SUCCESS("Created Production Units: Kitchen (FOOD), Bar (DRINKS)"))

        # ── Try running the menu seed if it hasn't been done ──
        menu_count = __import__("apps.menu.models", fromlist=["MenuItem"]).MenuItem.objects.filter(menu=menu).count()
        if menu_count == 0:
            from apps.menu.management.commands.seed_menu_catalog import Command as MenuSeed

            MenuSeed().handle(force=True)
        else:
            self.stdout.write(f"Menu already has {menu_count} items — skipping seed.")

        # ── Summary ──
        self.stdout.write(self.style.SUCCESS("── POS setup complete ──"))
        self.stdout.write(f"  Restaurant: {restaurant.company}")
        self.stdout.write(f"  Tax Template: {vat.title} (is_default={vat.is_default})")
        self.stdout.write(f"  POS Profile: {profile.name} (warehouse={profile.warehouse})")
        self.stdout.write(f"  Payment Methods: {', '.join(str(p) for p in profile.payments.all())}")
        self.stdout.write(f"  Production Units: Kitchen={pu_kitchen.department}, Bar={pu_bar.department}")
        self.stdout.write(f"  Tables: {Table.objects.filter(room=room).count()}")
        self.stdout.write(f"  Menu items: {menu_count}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Open http://localhost:8000/pos/ to test the POS screen"))

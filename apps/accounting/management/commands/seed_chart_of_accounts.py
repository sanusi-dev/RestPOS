"""Seed the chart of accounts for visual testing and go-live.

Idempotent. Creates the account tree, cost centers, the current-year fiscal
year, and wires the Restaurant accounting FKs, warehouse accounts,
production-unit income accounts, and payment GL mappings.

Usage:
    make manage ARGS='seed_chart_of_accounts'
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Seed the chart of accounts, cost centers, fiscal year, and GL wiring."

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.accounting.models import CostCenter, FiscalYear, LedgerAccount
        from apps.inventory.models import Warehouse
        from apps.payments.models import ModeOfPayment, PaymentGLMapping
        from apps.settings.models import ProductionUnit, Restaurant

        assets = LedgerAccount.objects.get_or_create(
            name="Assets",
            defaults={
                "is_group": True,
                "root_type": LedgerAccount.ASSET,
                "report_type": LedgerAccount.BALANCE_SHEET,
            },
        )[0]
        bank_group = LedgerAccount.objects.get_or_create(
            name="Bank Accounts",
            defaults={
                "parent": assets,
                "is_group": True,
                "root_type": LedgerAccount.ASSET,
                "report_type": LedgerAccount.BALANCE_SHEET,
            },
        )[0]
        cash_account = LedgerAccount.objects.get_or_create(
            name="Cash Account",
            defaults={
                "parent": assets,
                "is_group": False,
                "root_type": LedgerAccount.ASSET,
                "report_type": LedgerAccount.BALANCE_SHEET,
                "account_type": LedgerAccount.ACCOUNT_TYPE_CASH,
            },
        )[0]
        electronic_account = LedgerAccount.objects.get_or_create(
            name="Electronic Account",
            defaults={
                "parent": bank_group,
                "is_group": False,
                "root_type": LedgerAccount.ASSET,
                "report_type": LedgerAccount.BALANCE_SHEET,
                "account_type": LedgerAccount.ACCOUNT_TYPE_BANK,
            },
        )[0]

        income = LedgerAccount.objects.get_or_create(
            name="Income",
            defaults={
                "is_group": True,
                "root_type": LedgerAccount.INCOME,
                "report_type": LedgerAccount.PROFIT_AND_LOSS,
            },
        )[0]
        food_sales = LedgerAccount.objects.get_or_create(
            name="Food Sales",
            defaults={
                "parent": income,
                "is_group": False,
                "root_type": LedgerAccount.INCOME,
                "report_type": LedgerAccount.PROFIT_AND_LOSS,
                "account_type": LedgerAccount.ACCOUNT_TYPE_INCOME,
            },
        )[0]
        drinks_sales = LedgerAccount.objects.get_or_create(
            name="Drinks Sales",
            defaults={
                "parent": income,
                "is_group": False,
                "root_type": LedgerAccount.INCOME,
                "report_type": LedgerAccount.PROFIT_AND_LOSS,
                "account_type": LedgerAccount.ACCOUNT_TYPE_INCOME,
            },
        )[0]

        expenses = LedgerAccount.objects.get_or_create(
            name="Expenses",
            defaults={
                "is_group": True,
                "root_type": LedgerAccount.EXPENSE,
                "report_type": LedgerAccount.PROFIT_AND_LOSS,
            },
        )[0]
        cogs = LedgerAccount.objects.get_or_create(
            name="Cost of Goods Sold",
            defaults={
                "parent": expenses,
                "is_group": False,
                "root_type": LedgerAccount.EXPENSE,
                "report_type": LedgerAccount.PROFIT_AND_LOSS,
                "account_type": LedgerAccount.ACCOUNT_TYPE_COGS,
            },
        )[0]
        round_off = LedgerAccount.objects.get_or_create(
            name="Round Off",
            defaults={
                "parent": expenses,
                "is_group": False,
                "root_type": LedgerAccount.EXPENSE,
                "report_type": LedgerAccount.PROFIT_AND_LOSS,
                "account_type": LedgerAccount.ACCOUNT_TYPE_ROUND_OFF,
            },
        )[0]

        equity = LedgerAccount.objects.get_or_create(
            name="Equity",
            defaults={
                "is_group": True,
                "root_type": LedgerAccount.EQUITY,
                "report_type": LedgerAccount.BALANCE_SHEET,
            },
        )[0]
        LedgerAccount.objects.get_or_create(
            name="Owner's Equity",
            defaults={
                "parent": equity,
                "is_group": False,
                "root_type": LedgerAccount.EQUITY,
                "report_type": LedgerAccount.BALANCE_SHEET,
                "account_type": LedgerAccount.ACCOUNT_TYPE_EQUITY,
            },
        )

        kitchen_cc = CostCenter.objects.get_or_create(
            name="Kitchen",
            defaults={"is_group": False},
        )[0]
        bar_cc = CostCenter.objects.get_or_create(
            name="Bar",
            defaults={"is_group": False},
        )[0]

        today = date.today()
        fiscal_year = FiscalYear.objects.filter(disabled=False).first()
        if fiscal_year is None:
            fiscal_year = FiscalYear.objects.create(
                name=str(today.year),
                year_start_date=date(today.year, 1, 1),
                year_end_date=date(today.year, 12, 31),
            )

        # Wire production units, warehouses, and the Restaurant singleton.
        for unit in ProductionUnit.objects.all():
            if unit.income_account_id:
                continue
            if unit.department == ProductionUnit.FOOD:
                unit.income_account = food_sales
            elif unit.department == ProductionUnit.DRINKS:
                unit.income_account = drinks_sales
            else:
                continue
            unit.save(update_fields=["income_account", "updated_at"])

        # Inventory stock leaves per warehouse (credited at settle-time COGS).
        stock_group = LedgerAccount.objects.get_or_create(
            name="Inventory Stock",
            defaults={
                "parent": assets,
                "is_group": True,
                "root_type": LedgerAccount.ASSET,
                "report_type": LedgerAccount.BALANCE_SHEET,
            },
        )[0]
        for warehouse in Warehouse.objects.all():
            account = warehouse.account
            if account is None or account.account_type != LedgerAccount.ACCOUNT_TYPE_STOCK:
                account, _ = LedgerAccount.objects.get_or_create(
                    name=f"Stock in Hand — {warehouse.name}",
                    defaults={
                        "parent": stock_group,
                        "is_group": False,
                        "root_type": LedgerAccount.ASSET,
                        "report_type": LedgerAccount.BALANCE_SHEET,
                        "account_type": LedgerAccount.ACCOUNT_TYPE_STOCK,
                    },
                )
                warehouse.account = account
                warehouse.save(update_fields=["account", "updated_at"])

        # Supplier payables (Phase 2 §4.1): a dedicated payable leaf under
        # Liabilities plus a stock-in-hand default under the Inventory Stock
        # group, wired onto the Restaurant singleton.
        liabilities = LedgerAccount.objects.get_or_create(
            name="Liabilities",
            defaults={
                "is_group": True,
                "root_type": LedgerAccount.LIABILITY,
                "report_type": LedgerAccount.BALANCE_SHEET,
            },
        )[0]
        payable_account = LedgerAccount.objects.get_or_create(
            name="Accounts Payable",
            defaults={
                "parent": liabilities,
                "is_group": False,
                "root_type": LedgerAccount.LIABILITY,
                "report_type": LedgerAccount.BALANCE_SHEET,
            },
        )[0]
        stock_in_hand = LedgerAccount.objects.filter(
            parent=stock_group,
            is_group=False,
            account_type=LedgerAccount.ACCOUNT_TYPE_STOCK,
        ).first()
        if stock_in_hand is None:
            stock_in_hand = LedgerAccount.objects.get_or_create(
                name="Stock in Hand",
                defaults={
                    "parent": stock_group,
                    "is_group": False,
                    "root_type": LedgerAccount.ASSET,
                    "report_type": LedgerAccount.BALANCE_SHEET,
                    "account_type": LedgerAccount.ACCOUNT_TYPE_STOCK,
                },
            )[0]

        restaurant = Restaurant.load()
        if restaurant is not None:
            changed = []
            for field, value in [
                ("default_income_account", food_sales),
                ("default_expense_account", cogs),
                ("round_off_account", round_off),
                ("account_for_change_amount", cash_account),
                ("write_off_account", round_off),
                ("wastage_account", cogs),
                ("cash_shortage_account", cogs),
                ("cash_over_short_account", round_off),
                ("cost_center", kitchen_cc),
                ("default_payable_account", payable_account),
                ("default_stock_in_hand_account", stock_in_hand),
            ]:
                if getattr(restaurant, f"{field}_id") is None:
                    setattr(restaurant, field, value)
                    changed.append(field)
            if changed:
                restaurant.save(update_fields=changed + ["updated_at"])

        # Payment GL mappings now reference ledger accounts.
        for mode in ModeOfPayment.objects.all():
            account = cash_account if mode.type == ModeOfPayment.TYPE_CASH else electronic_account
            mapping, created = PaymentGLMapping.objects.get_or_create(
                mode_of_payment=mode,
                defaults={"default_account": account},
            )
            if not created and mapping.default_account_id is None:
                mapping.default_account = account
                mapping.save(update_fields=["default_account", "updated_at"])

        self.stdout.write(self.style.SUCCESS("── Chart of accounts seeded ──"))
        self.stdout.write(f"  Fiscal year: {fiscal_year.name}")
        self.stdout.write(f"  Cash account: {cash_account.name}")
        self.stdout.write(f"  Electronic account: {electronic_account.name}")
        self.stdout.write(f"  Income: {food_sales.name} / {drinks_sales.name}")
        self.stdout.write(f"  Cost centers: {kitchen_cc.name} / {bar_cc.name}")

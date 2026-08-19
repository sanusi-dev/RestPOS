"""Shared helpers for payments tests — ledger accounts for GL mappings."""

from apps.accounting.models import LedgerAccount


def create_payment_accounts():
    """Create a minimal Assets tree with cash and bank leaves for mapping tests."""
    assets = LedgerAccount.objects.create(
        name="Assets (payments test)",
        is_group=True,
        root_type=LedgerAccount.ASSET,
        report_type=LedgerAccount.BALANCE_SHEET,
    )
    bank_group = LedgerAccount.objects.create(
        name="Bank Accounts (payments test)",
        parent=assets,
        is_group=True,
        root_type=LedgerAccount.ASSET,
        report_type=LedgerAccount.BALANCE_SHEET,
    )
    cash = LedgerAccount.objects.create(
        name="Cash in Hand (payments test)",
        parent=assets,
        root_type=LedgerAccount.ASSET,
        report_type=LedgerAccount.BALANCE_SHEET,
        account_type=LedgerAccount.ACCOUNT_TYPE_CASH,
    )
    bank = LedgerAccount.objects.create(
        name="Bank Clearing (payments test)",
        parent=bank_group,
        root_type=LedgerAccount.ASSET,
        report_type=LedgerAccount.BALANCE_SHEET,
        account_type=LedgerAccount.ACCOUNT_TYPE_BANK,
    )
    return {"assets": assets, "bank_group": bank_group, "cash": cash, "bank": bank}

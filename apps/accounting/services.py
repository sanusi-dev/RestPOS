"""GL posting services — order settlement, cancellation, and refund postings.

The Order is the accounting document: GL posts at order settle and reverses
at order cancel/return. Manual journals and cash variance postings also flow
through here.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.orders.models import SUBMITTED
from apps.payments.models import PaymentGLMapping
from apps.settings.models import Restaurant

from .models import GLEntry, JournalEntry, JournalEntryAccount

TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# Account chain resolution
# ---------------------------------------------------------------------------


def _income_account_for(item_group, department):
    """Resolve the income account: ItemGroup → ProductionUnit → Restaurant default."""
    from apps.settings.models import ProductionUnit

    if item_group is not None and item_group.income_account_id:
        return item_group.income_account
    unit = ProductionUnit.objects.filter(department=department).select_related("income_account").first()
    if unit is not None and unit.income_account_id:
        return unit.income_account
    return None


def _expense_account_for(item_group):
    if item_group is not None and item_group.expense_account_id:
        return item_group.expense_account
    return None


def _resolve_required_account(account, *, label):
    if account is None:
        raise ValidationError(f"{label} is not configured.")
    if account.disabled:
        raise ValidationError(f"{label} ({account.name}) is disabled.")
    if not account.is_leaf:
        raise ValidationError(f"{label} ({account.name}) must be a leaf account.")
    return account


def _resolve_payment_account(mode):
    try:
        mapping = PaymentGLMapping.objects.select_related("default_account").get(mode_of_payment=mode)
    except PaymentGLMapping.DoesNotExist:
        raise ValidationError(f"Payment mode {mode.name} has no GL mapping.") from None
    account = mapping.default_account
    if account is None:
        raise ValidationError(f"Payment mode {mode.name} has no GL mapping.")
    if account.disabled:
        raise ValidationError(f"Payment mode {mode.name}'s GL account ({account.name}) is disabled.")
    if not account.is_leaf:
        raise ValidationError(f"Payment mode {mode.name}'s GL account ({account.name}) must be a leaf account.")
    return account


# ---------------------------------------------------------------------------
# Order GL
# ---------------------------------------------------------------------------


def _order_lines_with_accounts(order):
    """Return order lines with their resolved income/expense accounts."""
    from apps.inventory.models import ItemGroup

    lines = list(order.items.select_related("item__item_group", "item").all())
    groups = {
        g.pk: g
        for g in ItemGroup.objects.filter(pk__in={line.item.item_group_id for line in lines}).select_related(
            "income_account", "expense_account"
        )
    }
    result = []
    for line in lines:
        group = groups.get(line.item.item_group_id)
        department = line.department or line.item.department
        result.append(
            {
                "line": line,
                "group": group,
                "department": department,
            }
        )
    return result


def _income_legs(order, rows):
    """Build income GL rows keyed by resolved income account, merging per account."""
    from apps.settings.models import Restaurant

    settings = Restaurant.load()
    default_income = settings.default_income_account if settings else None
    per_account = {}
    for row in rows:
        account = _income_account_for(row["group"], row["department"]) or default_income
        account = _resolve_required_account(account, label="The default income account")
        amount = row["line"].amount
        per_account[account.pk] = {
            "account": account,
            "credit": per_account.get(account.pk, {}).get("credit", Decimal("0")) + amount,
        }
    return list(per_account.values())


def _payment_legs(order, settings):
    """Build payment GL rows (debits), reducing change once on the change account."""
    change_left = order.change_amount or Decimal("0")
    change_account = None
    if change_left:
        change_account = _resolve_required_account(
            settings.account_for_change_amount if settings else None,
            label="The change account",
        )
    rows = []
    for payment in order.payments.select_related("mode_of_payment").all():
        account = _resolve_payment_account(payment.mode_of_payment)
        amount = payment.amount
        if change_left and account.pk == change_account.pk:
            reduction = min(amount, change_left)
            amount -= reduction
            change_left -= reduction
        if amount != 0:
            rows.append({"account": account, "debit": amount})
    if change_left:
        raise ValidationError("Change could not be applied to a matching payment account.")
    return rows


def _rounding_leg(order, settings):
    """Round-off row: credit positive adjustment, debit negative."""
    amount = order.rounding_adjustment
    if not amount:
        return []
    account = _resolve_required_account(settings.round_off_account, label="The round-off account")
    if amount > 0:
        return [{"account": account, "credit": amount}]
    return [{"account": account, "debit": -amount}]


def _cogs_legs(order, rows, settings):
    """COGS from settle-time drink deductions — credited to the warehouse account."""
    from apps.inventory.models import StockLedgerEntry

    default_expense = settings.default_expense_account if settings else None
    sle_rows = StockLedgerEntry.objects.filter(
        voucher_type="POS Order",
        voucher_no=str(order.pk),
        quantity__lt=0,
    ).select_related("item")
    per_account = {}
    for sle in sle_rows:
        line = next((r for r in rows if r["line"].item_id == sle.item_id), None)
        if line is None:
            continue
        account = _expense_account_for(line["group"]) or default_expense
        if account is None:
            raise ValidationError("The default expense account is not configured.")
        account = _resolve_required_account(account, label="The default expense account")
        value = (abs(sle.quantity) * sle.unit_rate).quantize(TWO_PLACES)
        per_account[account.pk] = {
            "account": account,
            "debit": per_account.get(account.pk, {}).get("debit", Decimal("0")) + value,
        }
    if not per_account:
        return []
    total_value = sum((row["debit"] for row in per_account.values()), Decimal("0")).quantize(TWO_PLACES)
    warehouse_account = _resolve_required_account(
        order.stock_warehouse.account if order.stock_warehouse_id else None,
        label="The warehouse account",
    )
    return [{"account": row["account"], "debit": row["debit"]} for row in per_account.values()] + [
        {"account": warehouse_account, "credit": total_value}
    ]


def _merge_rows(rows):
    """Merge GL rows sharing account/against/fiscal-year/cost-center."""
    merged = {}
    for row in rows:
        key = (row.get("account").pk, row.get("against", ""), row.get("cost_center", None))
        if key in merged:
            merged[key]["debit"] = merged[key].get("debit", Decimal("0")) + row.get("debit", Decimal("0"))
            merged[key]["credit"] = merged[key].get("credit", Decimal("0")) + row.get("credit", Decimal("0"))
        else:
            merged[key] = {
                "account": row.get("account"),
                "against": row.get("against", ""),
                "cost_center": row.get("cost_center"),
                "debit": row.get("debit", Decimal("0")),
                "credit": row.get("credit", Decimal("0")),
            }
    result = []
    for row in merged.values():
        net = (row["debit"] or Decimal("0")) - (row["credit"] or Decimal("0"))
        if net > 0:
            result.append({**row, "debit": net, "credit": Decimal("0")})
        elif net < 0:
            result.append({**row, "debit": Decimal("0"), "credit": -net})
    return result


@transaction.atomic
def post_order_gl(order):
    """Post GL entries for a settled order. Runs inside settle_order's atomic block.

    All entries carry voucher_type="Order", voucher_no=invoice_number.
    Settlement fails closed when the required account chain is missing.
    """
    if order.status != SUBMITTED:
        raise ValidationError("Only submitted orders can be posted to the GL.")
    if order.is_return:
        # Returns post via the refund flow, not here.
        return
    if GLEntry.objects.filter(voucher_type="Order", voucher_no=order.invoice_number, is_cancelled=False).exists():
        return  # already posted — idempotent
    settings = Restaurant.load()
    if settings is None:
        raise ValidationError("Restaurant settings are not configured.")
    cost_center = settings.cost_center if settings.cost_center_id else None
    rows = _order_lines_with_accounts(order)

    legs = []
    legs.extend(_income_legs(order, rows))
    legs.extend(_payment_legs(order, settings))
    legs.extend(_rounding_leg(order, settings))
    legs.extend(_cogs_legs(order, rows, settings))

    # Build `against` (balancing account names) and merge.
    against = ", ".join(row["account"].name for row in legs if row.get("credit"))
    for row in legs:
        row["against"] = against
    merged = _merge_rows(legs)

    if not merged:
        return
    GLEntry.post(
        posting_date=order.posting_date,
        rows=merged,
        voucher_type="Order",
        voucher_no=order.invoice_number,
        remarks=f"Order {order.invoice_number}",
        cost_center=cost_center,
    )


@transaction.atomic
def reverse_order_gl(order, posting_date=None):
    """Post mirror-negated GL entries for a cancelled order or a return.

    Marks the original settle-time entries cancelled and writes negated rows.
    Reversals post on the day they occur (default: today) — corrections never
    retroactively alter the period of the original posting.
    """
    originals = GLEntry.objects.filter(voucher_type="Order", voucher_no=order.invoice_number, is_cancelled=False)
    if not originals.exists():
        return
    for gl in originals:
        gl.is_cancelled = True
        gl.save(update_fields=["is_cancelled", "updated_at"])
    GLEntry.post(
        posting_date=posting_date or timezone.localdate(),
        rows=[
            {
                "account": gl.account,
                "cost_center": gl.cost_center,
                "debit": gl.credit,
                "credit": gl.debit,
                "against": gl.against,
            }
            for gl in originals
        ],
        voucher_type="Order",
        voucher_no=order.invoice_number,
        remarks="Reversal",
        cost_center=None,
    )


# ---------------------------------------------------------------------------
# Refund GL
# ---------------------------------------------------------------------------


def _is_drink_line(line):
    return (line.department or getattr(line.item, "department", None)) == "DRINKS"


def _settle_time_rate(source_order, item):
    """WAC at the source order's settle-time stock deductions."""
    from apps.inventory.models import StockLedgerEntry

    sles = list(
        StockLedgerEntry.objects.filter(
            voucher_type="POS Order",
            voucher_no=str(source_order.pk),
            item=item,
            quantity__lt=0,
        )
    )
    if not sles:
        raise ValidationError(f"Settle-time valuation rate for {item.item_name} cannot be resolved.")
    qty = sum((abs(sle.quantity) for sle in sles), Decimal("0"))
    value = sum((abs(sle.quantity) * sle.unit_rate for sle in sles), Decimal("0"))
    if qty <= 0:
        raise ValidationError(f"Settle-time valuation rate for {item.item_name} cannot be resolved.")
    return value / qty


def _current_wac_for_return(return_order, item):
    """Current WAC at return time — from restore SLE or Bin."""
    from apps.inventory.models import Bin, StockLedgerEntry

    # Prefer the restore SLE created by _restore_stock (POS Return) — business date is posting_date.
    restore = (
        StockLedgerEntry.objects.filter(
            voucher_type="POS Return",
            voucher_no=str(return_order.pk),
            item=item,
            quantity__gt=0,
        )
        .order_by("-posting_date", "-posting_datetime", "-pk")
        .first()
    )
    if restore is not None:
        return restore.unit_rate
    # Not restockable has no restore — use Bin's current WAC
    if return_order.stock_warehouse_id:
        bin_obj = Bin.objects.filter(item=item, warehouse=return_order.stock_warehouse).first()
        if bin_obj and bin_obj.valuation_rate:
            return bin_obj.valuation_rate
    # Fallback to original sale rate
    return _settle_time_rate(return_order.return_against, item)


def _plug_round_off(rows, settings):
    """Put any debit/credit remainder on the round-off account so the batch balances."""
    debit = sum((row.get("debit") or Decimal("0") for row in rows), Decimal("0"))
    credit = sum((row.get("credit") or Decimal("0") for row in rows), Decimal("0"))
    diff = (debit - credit).quantize(TWO_PLACES)
    if not diff:
        return rows
    account = _resolve_required_account(
        settings.round_off_account if settings else None,
        label="The round-off account",
    )
    if diff > 0:
        rows.append({"account": account, "credit": diff})
    else:
        rows.append({"account": account, "debit": -diff})
    return rows


@transaction.atomic
def post_refund_gl(return_order):
    """Post refund GL rebuilt from the returned lines, payments, and wastage.

    Income reverses per returned line. Payment credits follow the return's
    OrderPayment rows. Drink lines reverse COGS at the settle-time outgoing
    rate; not-restockable drink lines also post Dr wastage / Cr warehouse.
    """
    if return_order.status != SUBMITTED or not return_order.is_return:
        raise ValidationError("Only submitted return orders can be posted to the GL.")
    source = return_order.return_against
    if source is None:
        raise ValidationError("The return order has no source order.")
    if GLEntry.objects.filter(
        voucher_type="Order", voucher_no=return_order.invoice_number, is_cancelled=False
    ).exists():
        return  # idempotent

    if not GLEntry.objects.filter(voucher_type="Order", voucher_no=source.invoice_number, is_cancelled=False).exists():
        return

    settings = Restaurant.load()
    if settings is None:
        raise ValidationError("Restaurant settings are not configured.")
    cost_center = settings.cost_center if settings.cost_center_id else None
    lines = list(return_order.items.select_related("item__item_group", "item").all())
    if not lines:
        raise ValidationError("The return has no refundable value.")

    rows = []
    income_rows = _income_legs(return_order, _order_lines_with_accounts(return_order))
    for row in income_rows:
        amount = abs(row.get("credit") or row.get("debit") or Decimal("0"))
        if amount:
            rows.append({"account": row["account"], "debit": amount, "cost_center": cost_center})

    for payment in return_order.payments.select_related("mode_of_payment").all():
        amount = abs(payment.amount)
        if amount:
            rows.append(
                {
                    "account": _resolve_payment_account(payment.mode_of_payment),
                    "credit": amount,
                    "cost_center": cost_center,
                }
            )

    default_expense = settings.default_expense_account if settings else None
    warehouse_account = None
    wastage_account = None
    drink_returns = [line for line in lines if _is_drink_line(line)]
    if drink_returns:
        warehouse_account = _resolve_required_account(
            return_order.stock_warehouse.account if return_order.stock_warehouse_id else None,
            label="The warehouse account",
        )
    if any(line.not_restockable for line in drink_returns):
        wastage_account = _resolve_required_account(
            settings.wastage_account if settings else None,
            label="The wastage account",
        )

    for line in drink_returns:
        rate = _current_wac_for_return(return_order, line.item)
        value = (abs(line.qty) * rate).quantize(TWO_PLACES)
        if not value:
            continue
        expense = _expense_account_for(line.item.item_group) or default_expense
        expense = _resolve_required_account(expense, label="The default expense account")
        rows.append({"account": expense, "credit": value, "cost_center": cost_center})
        rows.append({"account": warehouse_account, "debit": value, "cost_center": cost_center})
        if line.not_restockable:
            rows.append(
                {
                    "account": wastage_account,
                    "debit": value,
                    "cost_center": cost_center,
                    "against": warehouse_account.name,
                }
            )
            rows.append(
                {
                    "account": warehouse_account,
                    "credit": value,
                    "cost_center": cost_center,
                    "against": wastage_account.name,
                }
            )

    rows = _plug_round_off(_merge_rows(rows), settings)
    if not rows:
        return
    against = ", ".join(row["account"].name for row in rows if row.get("credit"))
    for row in rows:
        row.setdefault("against", against)
    GLEntry.post(
        posting_date=return_order.posting_date,
        rows=_merge_rows(rows),
        voucher_type="Order",
        voucher_no=return_order.invoice_number,
        remarks=f"Refund of {source.invoice_number}",
        cost_center=cost_center,
    )


# ---------------------------------------------------------------------------
# Cash variance posting (Phase 6 §4.5)
# ---------------------------------------------------------------------------


@transaction.atomic
def post_cash_variance_gl(closing):
    """Post a JournalEntry for a closing entry's short/excess variance.

    Shortage → Dr shortage account / Cr cash account.
    Excess → Dr cash account / Cr over-short account.
    Only posts when the account matching the variance sign is configured;
    otherwise the variance stays visible on the close with no posting.
    """
    from apps.staff.models import POSClosingEntry

    if closing.status != POSClosingEntry.SUBMITTED or not closing.total_short_excess:
        return None
    settings = Restaurant.load()
    if settings is None:
        return None
    variance = closing.total_short_excess
    if variance < 0:
        account = settings.cash_shortage_account
        label = "The cash shortage account"
    else:
        account = settings.cash_over_short_account
        label = "The cash over-short account"
    if account is None:
        return None  # no automatic posting when the matching account is unconfigured
    account = _resolve_required_account(account, label=label)

    from apps.payments.models import ModeOfPayment

    cash_mode = (
        ModeOfPayment.objects.filter(
            type=ModeOfPayment.TYPE_CASH,
            enabled=True,
            gl_mapping__isnull=False,
        )
        .select_related("gl_mapping")
        .first()
    )
    if cash_mode is None:
        raise ValidationError("No enabled cash payment mode with a GL mapping is configured.")
    cash_account = _resolve_payment_account(cash_mode)

    journal = JournalEntry.objects.create(
        voucher_type=JournalEntry.JOURNAL,
        posting_date=closing.posting_date,
        remark=f"Cash variance for closing entry #{closing.pk}",
    )
    if variance < 0:
        JournalEntryAccount.objects.create(
            journal_entry=journal,
            account=account,
            debit=abs(variance),
            remarks="Cash shortage",
        )
        JournalEntryAccount.objects.create(
            journal_entry=journal,
            account=cash_account,
            credit=abs(variance),
            remarks="Cash shortage",
        )
    else:
        JournalEntryAccount.objects.create(
            journal_entry=journal,
            account=cash_account,
            debit=variance,
            remarks="Cash excess",
        )
        JournalEntryAccount.objects.create(
            journal_entry=journal,
            account=account,
            credit=variance,
            remarks="Cash excess",
        )
    journal.submit()
    return journal


# ---------------------------------------------------------------------------
# Supplier payables GL (Phase 2 §4.1)
# ---------------------------------------------------------------------------


def _payable_account_for(supplier, settings, label="The default payable account"):
    """Resolve the payable account: per-supplier override → Restaurant default."""
    account = supplier.payable_account if supplier.payable_account_id else None
    if account is None:
        account = settings.default_payable_account if settings else None
    return _resolve_required_account(account, label=label)


def _reverse_gl(voucher_type, voucher_no, remarks="Reversal"):
    """Mark a voucher's GL rows cancelled and post mirrored negated rows (today)."""
    originals = list(GLEntry.objects.filter(voucher_type=voucher_type, voucher_no=voucher_no, is_cancelled=False))
    if not originals:
        return
    for gl in originals:
        gl.is_cancelled = True
        gl.save(update_fields=["is_cancelled", "updated_at"])
    GLEntry.post(
        posting_date=timezone.localdate(),
        rows=[
            {
                "account": gl.account,
                "cost_center": gl.cost_center,
                "debit": gl.credit,
                "credit": gl.debit,
                "against": gl.against,
            }
            for gl in originals
        ],
        voucher_type=voucher_type,
        voucher_no=voucher_no,
        remarks=remarks,
    )


@transaction.atomic
def post_supplier_invoice_gl(invoice):
    """Post the supplier invoice: Dr GRNI/expense, Cr payable. Idempotent."""
    if GLEntry.objects.filter(
        voucher_type="Supplier Invoice", voucher_no=invoice.invoice_number, is_cancelled=False
    ).exists():
        return
    settings = Restaurant.load()
    if settings is None:
        raise ValidationError("Restaurant settings are not configured.")
    cost_center = settings.cost_center if settings.cost_center_id else None

    stock_total = Decimal("0")
    expense_total = Decimal("0")
    stock_rows = []
    expense_rows = []
    for line in invoice.items.select_related("item__item_group", "expense_account", "source_receipt_line").all():
        if line.item_id:
            # Stock lines must link to a purchase receipt (GRNI clearing)
            if not invoice.purchase_receipt_id:
                raise ValidationError("Supplier invoices with stock lines must link to a purchase receipt.")
            # Enforce rate/qty equality if linked to receipt line
            if line.source_receipt_line_id and (
                line.qty != line.source_receipt_line.received_qty or line.rate != line.source_receipt_line.rate
            ):
                raise ValidationError("Stock line rate/quantity must match the receipt line.")
            account = settings.stock_received_but_not_billed_account if settings else None
            account = _resolve_required_account(account, label="The stock received but not billed account")
            stock_total += line.amount
            stock_rows.append({"account": account, "debit": line.amount, "cost_center": cost_center})
        else:
            expense_rows.append(
                {
                    "account": _resolve_required_account(line.expense_account, label="The line expense account"),
                    "debit": line.amount,
                    "cost_center": cost_center,
                }
            )
            expense_total += line.amount
    if not stock_rows and not expense_rows:
        raise ValidationError("Add at least one line before submitting.")

    payable = _payable_account_for(invoice.supplier, settings)
    legs = stock_rows + expense_rows + [{"account": payable, "credit": stock_total + expense_total}]
    against = payable.name
    for row in legs:
        row["against"] = against
    rows = _merge_rows(legs)

    GLEntry.post(
        posting_date=invoice.posting_date,
        rows=rows,
        voucher_type="Supplier Invoice",
        voucher_no=invoice.invoice_number,
        remarks=f"Supplier invoice {invoice.invoice_number}",
        cost_center=cost_center,
    )


@transaction.atomic
def cancel_supplier_invoice_gl(invoice):
    """Reverse the invoice's GL rows (mirrored negated rows, originals cancelled)."""
    _reverse_gl("Supplier Invoice", invoice.invoice_number)


@transaction.atomic
def post_supplier_payment_gl(payment):
    """Post the supplier payment: Dr payable, Cr cash/bank. Idempotent."""
    if GLEntry.objects.filter(
        voucher_type="Supplier Payment", voucher_no=payment.payment_number, is_cancelled=False
    ).exists():
        return
    settings = Restaurant.load()
    if settings is None:
        raise ValidationError("Restaurant settings are not configured.")
    payable = _payable_account_for(payment.supplier, settings)
    cash_account = _resolve_payment_account(payment.mode_of_payment)
    cost_center = settings.cost_center if settings.cost_center_id else None

    rows = [
        {"account": payable, "debit": payment.paid_amount, "against": cash_account.name, "cost_center": cost_center},
        {
            "account": cash_account,
            "credit": payment.paid_amount,
            "against": payable.name,
            "cost_center": cost_center,
        },
    ]
    GLEntry.post(
        posting_date=payment.posting_date,
        rows=rows,
        voucher_type="Supplier Payment",
        voucher_no=payment.payment_number,
        remarks=f"Payment to {payment.supplier.supplier_name}",
        cost_center=cost_center,
    )


@transaction.atomic
def cancel_supplier_payment_gl(payment):
    """Reverse the payment's GL rows (mirrored negated rows, originals cancelled)."""
    _reverse_gl("Supplier Payment", payment.payment_number)

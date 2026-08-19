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
    """Build payment GL rows (debits), reducing change on the cash account."""
    account_for_change = settings.account_for_change_amount if settings else None
    rows = []
    for payment in order.payments.select_related("mode_of_payment").all():
        account = _resolve_payment_account(payment.mode_of_payment)
        amount = payment.amount
        if account_for_change and account.pk == account_for_change.pk:
            amount -= order.change_amount
        if amount != 0:
            rows.append({"account": account, "debit": amount})
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
    # Aggregate per item: quantity and FIFO outgoing value from the settle-time SLEs.
    sle_rows = StockLedgerEntry.objects.filter(
        voucher_type="POS Order",
        voucher_no=str(order.pk),
        actual_qty__lt=0,
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
        value = (abs(sle.actual_qty) * sle.outgoing_rate).quantize(TWO_PLACES)
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
    return [row for row in merged.values() if row["debit"] or row["credit"]]


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
# Refund GL (Phase 6 §4.3)
# ---------------------------------------------------------------------------


def _refund_ratio(source, return_order):
    """Return the fraction of the source order being refunded (0 < ratio <= 1)."""
    source_total = source.grand_total or Decimal("1")
    refund_total = abs(return_order.grand_total)
    if refund_total == 0:
        raise ValidationError("The return has no refundable value.")
    ratio = (refund_total / source_total).quantize(Decimal("0.000001"))
    if ratio > Decimal("1"):
        raise ValidationError("Refund value exceeds the source order total.")
    return ratio


def _return_line_rate(return_order, line):
    """Best-available valuation rate for a return line (settle-time outgoing)."""
    from apps.inventory.models import StockLedgerEntry

    sle = (
        StockLedgerEntry.objects.filter(
            voucher_type="POS Return",
            voucher_no=str(return_order.pk),
            item=line.item,
        )
        .order_by("-pk")
        .first()
    )
    if sle is not None:
        return sle.incoming_rate
    bin_obj = line.item.bins.filter(warehouse=return_order.stock_warehouse).first()
    return bin_obj.valuation_rate if bin_obj else Decimal("0")


@transaction.atomic
def post_refund_gl(return_order):
    """Post mirror-negated GL entries for the refunded portion of a return.

    Mirrors the source order's settle legs scaled by the refund ratio, carrying
    the return's invoice number as voucher_no="Order". Restockable lines are
    restored via the existing "POS Return" SLE; the COGS leg reversal credits
    the warehouse account for the restored value. Non-restockable lines post
    wastage: Dr wastage account / Cr warehouse account at settle-time rate.
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

    settings = Restaurant.load()
    if settings is None:
        raise ValidationError("Restaurant settings are not configured.")

    ratio = _refund_ratio(source, return_order)
    source_gl = GLEntry.objects.filter(
        voucher_type="Order",
        voucher_no=source.invoice_number,
        is_cancelled=False,
    )
    if not source_gl.exists():
        # The source was never posted (e.g. pre-GL order) — nothing to mirror.
        return

    cost_center = settings.cost_center if settings.cost_center_id else None
    rows = []
    for gl in source_gl:
        rows.append(
            {
                "account": gl.account,
                "cost_center": gl.cost_center or cost_center,
                "debit": (gl.credit * ratio).quantize(TWO_PLACES),
                "credit": (gl.debit * ratio).quantize(TWO_PLACES),
                "against": gl.against,
            }
        )

    # Wastage: non-restockable return lines post Dr wastage / Cr warehouse at
    # the settle-time valuation rate (the value stays out of stock).
    wastage_account = settings.wastage_account if settings.wastage_account_id else None
    not_restockable_lines = list(return_order.items.select_related("item").filter(not_restockable=True))
    if not_restockable_lines:
        if wastage_account is None:
            raise ValidationError("The wastage account is not configured.")
        warehouse_account = _resolve_required_account(
            return_order.stock_warehouse.account if return_order.stock_warehouse_id else None,
            label="The warehouse account",
        )
        for line in not_restockable_lines:
            value = (abs(line.qty) * _return_line_rate(return_order, line)).quantize(TWO_PLACES)
            rows.append(
                {
                    "account": wastage_account,
                    "cost_center": cost_center,
                    "debit": value,
                    "against": warehouse_account.name,
                }
            )
            rows.append(
                {
                    "account": warehouse_account,
                    "cost_center": cost_center,
                    "credit": value,
                    "against": wastage_account.name,
                }
            )

    rows = _merge_rows(rows)
    if not rows:
        return
    GLEntry.post(
        posting_date=return_order.posting_date,
        rows=rows,
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
    """Post the supplier invoice: Dr stock-in-hand/expense, Cr payable. Idempotent."""
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
    for line in invoice.items.select_related("item__item_group", "expense_account").all():
        if line.item_id:
            group = line.item.item_group
            account = None
            if group is not None and group.expense_account_id:
                account = group.expense_account
            if account is None:
                account = settings.default_stock_in_hand_account if settings else None
            account = _resolve_required_account(account, label="The default stock-in-hand account")
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

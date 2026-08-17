"""Staff workflow services — shift closing logic shared across apps."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import OuterRef, Subquery, Sum
from django.utils import timezone

from apps.orders.models import SUBMITTED, Order, OrderItem, OrderPayment
from apps.payments.models import ModeOfPayment

from .models import ClosingPayment, OpeningPayment, POSClosingEntry, POSOpeningEntry


def collect_submitted_payment_totals(submitted_orders, payment_rows):
    """Return submitted payment totals per mode, net of cash change."""
    mode_ids = {payment.mode_of_payment_id for payment in payment_rows}
    if not mode_ids:
        return {}

    payment_totals = {
        row["mode_of_payment_id"]: row["total"] or Decimal("0")
        for row in OrderPayment.objects.filter(
            order__in=submitted_orders,
            mode_of_payment_id__in=mode_ids,
        )
        .values("mode_of_payment_id")
        .annotate(total=Sum("amount"))
    }
    cash_mode_ids = {
        payment.mode_of_payment_id
        for payment in payment_rows
        if payment.mode_of_payment.type == ModeOfPayment.TYPE_CASH
    }
    if not cash_mode_ids:
        return payment_totals

    cash_change_totals = {}
    cash_orders = (
        submitted_orders.filter(payments__mode_of_payment_id__in=cash_mode_ids)
        .values("payments__mode_of_payment_id", "pk", "change_amount")
        .distinct()
    )
    for row in cash_orders:
        mode_id = row["payments__mode_of_payment_id"]
        cash_change_totals[mode_id] = cash_change_totals.get(mode_id, Decimal("0")) + row["change_amount"]
    for mode_id, change_total in cash_change_totals.items():
        payment_totals[mode_id] = payment_totals.get(mode_id, Decimal("0")) - change_total
    return payment_totals


def expected_closing_amounts(open_shift, period_start, period_end):
    """Compute expected drawer amounts for each opening payment mode.

    Expected = opening float + payments collected in the period (cash change
    netted off), minus refunds of returns submitted in the period.
    """
    submitted_orders = Order.objects.submitted_in_shift(open_shift, period_start, period_end)
    opening_payments = list(open_shift.opening_payments.select_related("mode_of_payment").all())
    collected_by_mode = collect_submitted_payment_totals(submitted_orders, opening_payments)
    refunded_orders = Order.objects.filter(
        opening_entry=open_shift,
        status=SUBMITTED,
        is_return=True,
        submitted_at__gte=period_start,
        submitted_at__lte=period_end,
    )
    refund_rows = OrderPayment.objects.filter(order__in=refunded_orders)
    refund_by_mode = {
        row["mode_of_payment_id"]: abs(row["total"] or Decimal("0"))
        for row in refund_rows.values("mode_of_payment_id").annotate(total=Sum("amount")).order_by()
    }
    rows = []
    for opening_payment in opening_payments:
        collected = collected_by_mode.get(opening_payment.mode_of_payment_id, Decimal("0"))
        refunded = refund_by_mode.get(opening_payment.mode_of_payment_id, Decimal("0"))
        rows.append(
            {
                "mode": opening_payment.mode_of_payment,
                "opening_amount": opening_payment.opening_amount,
                "expected_amount": opening_payment.opening_amount + collected - refunded,
            }
        )
    return rows


def ensure_closing_draft(open_shift, cashier):
    """Return the draft closing entry for this shift, creating it only when needed."""
    closing = POSClosingEntry.objects.filter(
        opening_entry=open_shift,
        status=POSClosingEntry.DRAFT,
    ).first()
    if closing is not None:
        return closing
    closing = POSClosingEntry.objects.create(opening_entry=open_shift, cashier=cashier)
    ClosingPayment.objects.bulk_create(
        [
            ClosingPayment(
                closing_entry=closing,
                mode_of_payment=opening_payment.mode_of_payment,
                opening_amount=opening_payment.opening_amount,
                expected_amount=opening_payment.opening_amount,
                closing_amount=Decimal("0"),
            )
            for opening_payment in open_shift.opening_payments.all()
        ]
    )
    return closing


@transaction.atomic
def open_shift(cashier, opening_amounts, remarks=""):
    """Open a shift with the declared opening float per payment mode."""
    from apps.settings.models import Restaurant

    settings = Restaurant.objects.select_for_update().first()
    if settings is None:
        raise ValidationError("Restaurant settings are not configured.")
    open_exists = (
        POSOpeningEntry.objects.select_for_update()
        .filter(status=POSOpeningEntry.SUBMITTED, closing_entry__isnull=True)
        .order_by("period_start_date")
        .first()
    )
    if open_exists is not None:
        raise ValidationError("A shift is already open.")
    entry = POSOpeningEntry.objects.create(cashier=cashier, remarks=remarks.strip())
    OpeningPayment.objects.bulk_create(
        [
            OpeningPayment(opening_entry=entry, mode_of_payment=mode, opening_amount=amount)
            for mode, amount in opening_amounts.items()
        ]
    )
    entry.full_clean()
    entry.submit()
    return entry


@transaction.atomic
def submit_closing_entry(closing):
    """Compute expected amounts, validate, and close the opening entry."""
    if closing.status != POSClosingEntry.DRAFT:
        return
    locked = POSClosingEntry.objects.select_for_update().select_related("opening_entry").get(pk=closing.pk)
    opening = POSOpeningEntry.objects.select_for_update().get(pk=locked.opening_entry_id)
    if not opening.is_open:
        raise ValidationError("The opening shift is no longer open.")
    # Cut off at submit time so orders settled after the draft was opened are included.
    locked.period_end_date = timezone.now()
    opening_payments = list(opening.opening_payments.select_related("mode_of_payment").all())
    opening_modes = {op.mode_of_payment_id: op for op in opening_payments}
    closing_payments = list(locked.closing_payments.select_related("mode_of_payment").all())

    draft_count = Order.objects.open_drafts(opening).count()
    if draft_count:
        raise ValidationError(
            f"Close or settle {draft_count} open order{'s' if draft_count != 1 else ''} before closing the shift."
        )

    submitted_orders = Order.objects.submitted_in_shift(opening, locked.period_start_date, locked.period_end_date)
    # Drafts block the close above; returns are excluded because they are
    # handled by the deferred refund flow rather than drawer sales.
    item_totals = (
        OrderItem.objects.filter(order_id=OuterRef("pk")).values("order_id").annotate(total=Sum("qty")).values("total")
    )
    order_totals = submitted_orders.aggregate(
        total_quantity=Sum(Subquery(item_totals)),
        net_total=Sum("net_total"),
        grand_total=Sum("grand_total"),
    )
    locked.total_quantity = order_totals["total_quantity"] or Decimal("0")
    locked.net_total = order_totals["net_total"] or Decimal("0")
    locked.grand_total = order_totals["grand_total"] or Decimal("0")

    for cp in closing_payments:
        if cp.mode_of_payment_id not in opening_modes:
            raise ValidationError({"mode_of_payment": (f"{cp.mode_of_payment} was not declared at shift open.")})

    expected_by_mode = {
        row["mode"].pk: row
        for row in expected_closing_amounts(opening, locked.period_start_date, locked.period_end_date)
    }
    for cp in closing_payments:
        expected = expected_by_mode[cp.mode_of_payment_id]
        cp.opening_amount = expected["opening_amount"]
        cp.expected_amount = expected["expected_amount"]
        cp.difference = cp.closing_amount - cp.expected_amount
        cp.save(
            update_fields=[
                "opening_amount",
                "expected_amount",
                "difference",
                "updated_at",
            ]
        )
    locked.total_short_excess = sum((cp.difference for cp in closing_payments), Decimal("0"))
    locked.status = POSClosingEntry.SUBMITTED
    locked.save(
        update_fields=[
            "period_end_date",
            "total_quantity",
            "net_total",
            "grand_total",
            "total_short_excess",
            "status",
            "updated_at",
        ]
    )
    # Flip the opening entry to Closed
    opening.closing_entry = locked
    opening.period_end_date = locked.period_end_date
    opening.save(update_fields=["closing_entry", "period_end_date", "updated_at"])
    closing.refresh_from_db()

"""Staff workflow services — shift closing logic shared across apps."""

from decimal import Decimal

from django.db.models import Sum

from apps.orders.models import SUBMITTED, Order, OrderPayment
from apps.payments.models import ModeOfPayment

from .models import ClosingPayment, POSClosingEntry


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

    Expected = opening float + payments collected in the period. For cash,
    change given back to customers is netted off the collected total.
    """
    submitted_orders = Order.objects.filter(
        opening_entry=open_shift,
        status=SUBMITTED,
        is_return=False,
        submitted_at__gte=period_start,
        submitted_at__lte=period_end,
    )
    opening_payments = list(open_shift.opening_payments.select_related("mode_of_payment").all())
    collected_by_mode = collect_submitted_payment_totals(submitted_orders, opening_payments)
    rows = []
    for opening_payment in opening_payments:
        collected = collected_by_mode.get(opening_payment.mode_of_payment_id, Decimal("0"))
        rows.append(
            {
                "mode": opening_payment.mode_of_payment,
                "opening_amount": opening_payment.opening_amount,
                "expected_amount": opening_payment.opening_amount + collected,
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

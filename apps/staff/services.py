"""Staff workflow services — shift closing logic shared across apps."""

from decimal import Decimal

from django.db.models import Sum

from apps.orders.models import SUBMITTED, Order, OrderPayment
from apps.payments.models import ModeOfPayment

from .models import ClosingPayment, POSClosingEntry


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
    rows = []
    for opening_payment in open_shift.opening_payments.select_related("mode_of_payment").all():
        collected = OrderPayment.objects.filter(
            order__in=submitted_orders,
            mode_of_payment_id=opening_payment.mode_of_payment_id,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        if opening_payment.mode_of_payment.type == ModeOfPayment.TYPE_CASH:
            collected -= sum(
                (
                    order.change_amount
                    for order in submitted_orders.filter(
                        payments__mode_of_payment_id=opening_payment.mode_of_payment_id
                    ).distinct()
                ),
                Decimal("0"),
            )
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

"""Staff workflow services — shift closing logic shared across apps."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.orders.models import DRAFT, SUBMITTED, Order, OrderPayment
from apps.payments.models import ModeOfPayment

from .models import ClosingPayment, OpeningPayment, POSClosingEntry, POSOpeningEntry


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
    opening_modes = {
        op.mode_of_payment_id: op for op in opening.opening_payments.select_related("mode_of_payment").all()
    }

    draft_count = Order.objects.filter(opening_entry=opening, status=DRAFT, is_return=False).count()
    if draft_count:
        raise ValidationError(
            f"Close or settle {draft_count} open order{'s' if draft_count != 1 else ''} before closing the shift."
        )

    submitted_orders = Order.objects.filter(
        opening_entry=opening,
        status=SUBMITTED,
        is_return=False,
        submitted_at__gte=locked.period_start_date,
        submitted_at__lte=locked.period_end_date,
    )
    # Drafts block the close above; returns are excluded because they are
    # handled by the deferred refund flow rather than drawer sales.
    locked.total_quantity = submitted_orders.aggregate(total=Sum("items__qty"))["total"] or Decimal("0")
    locked.net_total = submitted_orders.aggregate(total=Sum("net_total"))["total"] or Decimal("0")
    locked.grand_total = submitted_orders.aggregate(total=Sum("grand_total"))["total"] or Decimal("0")

    expected_by_mode = {
        row["mode"].pk: row
        for row in expected_closing_amounts(opening, locked.period_start_date, locked.period_end_date)
    }
    for cp in locked.closing_payments.select_related("mode_of_payment").all():
        if cp.mode_of_payment_id not in opening_modes:
            raise ValidationError({"mode_of_payment": (f"{cp.mode_of_payment} was not declared at shift open.")})
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
    locked.total_short_excess = sum(
        (cp.difference for cp in locked.closing_payments.all()),
        Decimal("0"),
    )
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

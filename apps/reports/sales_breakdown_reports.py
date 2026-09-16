"""Dimension sales reports: per item, cashier, service type, and hour."""

from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import Coalesce, ExtractHour

from apps.orders.models import DINE_IN, SUBMITTED, TAKE_AWAY, OrderItem
from apps.users.models import CustomUser

from .models import DRINKS, FOOD
from .sales_reports import ZERO, _dept_totals, _q2, _sum_rows, submitted_orders


def _apply_item_filters(qs, *, department=None, item_group_id=None):
    if department:
        qs = qs.filter(department=department)
    if item_group_id:
        qs = qs.filter(item__item_group_id=item_group_id)
    return qs


def itemwise(date_from=None, date_to=None, *, department=None, item_group_id=None):
    """One row per item: qty, gross, refunded, net."""
    qs = _apply_item_filters(
        OrderItem.objects.filter(order__status=SUBMITTED),
        department=department,
        item_group_id=item_group_id,
    )
    if date_from:
        qs = qs.filter(order__posting_date__gte=date_from)
    if date_to:
        qs = qs.filter(order__posting_date__lte=date_to)
    buckets = (
        qs.values("item_id")
        .annotate(
            item_name=Max("item_name"),
            qty=Coalesce(Sum("qty"), ZERO),
            gross=Coalesce(Sum("amount", filter=Q(order__is_return=False)), ZERO),
            refunded=Coalesce(Sum("amount", filter=Q(order__is_return=True)), ZERO),
            net=Coalesce(Sum("amount"), ZERO),
        )
        .order_by("item_name")
    )
    rows = [
        {
            "item_id": row["item_id"],
            "item_name": row["item_name"],
            "qty": row["qty"] or ZERO,
            "gross": _q2(row["gross"]),
            "refunded": _q2(-(row["refunded"] or ZERO)),
            "net": _q2(row["net"]),
        }
        for row in buckets
    ]
    totals = _sum_rows(rows, keys=("qty", "gross", "refunded", "net"))
    return rows, totals


def employeewise(date_from=None, date_to=None):
    """One row per cashier (blank when unset): bills, net sales."""
    qs = submitted_orders(date_from, date_to)
    buckets = (
        qs.values("cashier_id")
        .annotate(
            bills=Count("pk"),
            net=Coalesce(Sum("rounded_total"), ZERO),
        )
        .order_by("cashier_id")
    )
    names = {
        user.pk: user.get_display_name()
        for user in CustomUser.objects.filter(pk__in=[row["cashier_id"] for row in buckets if row["cashier_id"]])
    }
    rows = [
        {
            "cashier_id": row["cashier_id"],
            "cashier_name": names.get(row["cashier_id"]) or "—",
            "bills": row["bills"],
            "net": _q2(row["net"]),
        }
        for row in buckets
    ]
    return rows, _sum_rows(rows, keys=("bills", "net"))


def servicewise(date_from=None, date_to=None):
    """One row each for DINE_IN and TAKE_AWAY."""
    qs = submitted_orders(date_from, date_to)
    dept = _dept_totals(qs, {"order_type": "order__order_type"})
    by_type = {
        row["order_type"]: row
        for row in qs.values("order_type").annotate(
            bills=Count("pk"),
            net=Coalesce(Sum("rounded_total"), ZERO),
        )
    }
    rows = []
    for order_type, label in ((DINE_IN, "Dine in"), (TAKE_AWAY, "Take away")):
        bucket = by_type.get(order_type, {"bills": 0, "net": ZERO})
        food = _q2(dept[(order_type,)].get(FOOD, ZERO))
        drinks = _q2(dept[(order_type,)].get(DRINKS, ZERO))
        rows.append(
            {
                "order_type": order_type,
                "label": label,
                "bills": bucket["bills"],
                "gross_food": food,
                "gross_drinks": drinks,
                "net": _q2(bucket["net"]),
            }
        )
    return rows, _sum_rows(rows, keys=("bills", "gross_food", "gross_drinks", "net"))


def timewise(date_from=None, date_to=None):
    """24 rows from posting_time hour 00–23."""
    qs = submitted_orders(date_from, date_to).annotate(hour=ExtractHour("posting_time"))
    by_hour = {
        int(row["hour"]): row
        for row in qs.values("hour").annotate(
            bills=Count("pk"),
            net=Coalesce(Sum("rounded_total"), ZERO),
        )
    }
    rows = []
    for hour in range(24):
        bucket = by_hour.get(hour, {"bills": 0, "net": ZERO})
        rows.append(
            {
                "hour": hour,
                "label": f"{hour:02d}:00",
                "bills": bucket["bills"],
                "net": _q2(bucket["net"]),
            }
        )
    return rows, _sum_rows(rows, keys=("bills", "net"))

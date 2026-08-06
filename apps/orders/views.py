"""Backoffice views for the orders app — order and KOT management."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import models as django_models
from django.db.models import Count, Prefetch, Q, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import printing
from .forms import POSOrderCancelForm
from .models import (
    DRAFT,
    KOT,
    KOT_PRINT_STATUS_CHOICES,
    KOT_PRINTED,
    KOT_TYPE_CHOICES,
    ORDER_TYPE_CHOICES,
    STATUS_CHOICES,
    SUBMITTED,
    TICKET_TYPE_CHOICES,
    Order,
)


@login_required
def orders_dashboard(request: HttpRequest) -> HttpResponse:
    """Render the orders and kitchen/bar ticket backoffice overview."""
    today = timezone.localdate()
    todays_orders = Order.objects.filter(posting_date=today)
    today_summary = todays_orders.aggregate(
        orders=Count("pk"),
        paid=Count("pk", filter=Q(status=SUBMITTED, is_paid=True)),
        cancelled=Count("pk", filter=Q(status="CANCELLED")),
        revenue=Sum("grand_total", filter=Q(status=SUBMITTED, is_paid=True)),
    )
    recent_orders = (
        Order.objects.select_related("cashier")
        .annotate(
            item_count=Count("items", distinct=True),
            ticket_count=Count("kots", distinct=True),
        )
        .order_by("-updated_at")[:8]
    )
    pending_tickets = (
        KOT.objects.select_related("order", "production_unit", "created_by")
        .filter(status=SUBMITTED, print_status="PENDING")
        .annotate(item_count=Count("items", distinct=True))
        .order_by("created_at")[:8]
    )
    context = {
        "today": today,
        "orders_today_count": today_summary["orders"],
        "paid_today_count": today_summary["paid"],
        "draft_count": Order.objects.filter(status=DRAFT).count(),
        "cancelled_today_count": today_summary["cancelled"],
        "today_revenue": today_summary["revenue"] or 0,
        "tickets_today_count": KOT.objects.filter(created_at__date=today).count(),
        "pending_ticket_count": KOT.objects.filter(status=SUBMITTED, print_status="PENDING").count(),
        "recent_orders": recent_orders,
        "pending_tickets": pending_tickets,
    }
    return render(request, "backoffice/orders/dashboard.html", context)


@login_required
def order_list(request: HttpRequest) -> HttpResponse:
    search = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()
    order_type_filter = request.GET.get("order_type", "").strip()

    orders = Order.objects.select_related("cashier").annotate(
        item_count=Count("items", distinct=True),
        ticket_count=Count("kots", distinct=True),
        pending_ticket_count=Count(
            "kots",
            filter=Q(kots__status=SUBMITTED, kots__print_status="PENDING"),
            distinct=True,
        ),
    )
    if search:
        search_query = django_models.Q(invoice_number__icontains=search) | django_models.Q(
            customer_name__icontains=search
        )
        order_number = search.removeprefix("#")
        if order_number.isdigit():
            search_query |= django_models.Q(order_number=int(order_number))
        orders = orders.filter(search_query)
    if status_filter:
        orders = orders.filter(status=status_filter)
    if order_type_filter:
        orders = orders.filter(order_type=order_type_filter)
    orders = orders.order_by("-updated_at")
    page_obj = Paginator(orders, 50).get_page(request.GET.get("page") or 1)

    return render(
        request,
        "backoffice/orders/order_list.html",
        {
            "orders": page_obj,
            "page_obj": page_obj,
            "search": search,
            "status_filter": status_filter,
            "order_type_filter": order_type_filter,
            "status_choices": STATUS_CHOICES,
            "order_type_choices": ORDER_TYPE_CHOICES,
        },
    )


@login_required
def order_detail(request: HttpRequest, pk: int) -> HttpResponse:
    ticket_queryset = KOT.objects.select_related("production_unit", "created_by").prefetch_related("items__item")
    order = get_object_or_404(
        Order.objects.select_related("cashier", "opening_entry").prefetch_related(
            "items__item__item_group",
            "payments__mode_of_payment",
            Prefetch("kots", queryset=ticket_queryset),
        ),
        pk=pk,
    )
    return render(
        request,
        "backoffice/orders/order_detail.html",
        {"order": order, "cancel_form": POSOrderCancelForm()},
    )


@login_required
@require_POST
def order_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    if not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
        messages.error(request, "Only managers can cancel orders.")
        return redirect("orders:order_detail", pk=pk)
    order = get_object_or_404(Order, pk=pk)
    form = POSOrderCancelForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose a cancellation reason before cancelling the order.")
        return redirect("orders:order_detail", pk=order.pk)
    try:
        cancellation_kots = order.cancel(
            form.cleaned_data["cancel_reason"],
            cancelled_by=request.user,
            reason_note=form.cleaned_data["cancel_reason_note"],
        )
    except ValidationError as e:
        messages.error(request, str(e.messages[0]) if e.messages else "Cancel failed.")
        return redirect("orders:order_detail", pk=order.pk)
    for cancellation_kot in cancellation_kots:
        result = printing.print_ticket(cancellation_kot)
        if result.success:
            cancellation_kot.print_status = KOT_PRINTED
            cancellation_kot.save(update_fields=["print_status", "updated_at"])
        else:
            messages.warning(request, f"Cancellation ticket for {result.ticket_type} remains pending.")
    messages.success(request, f"Order {order.invoice_number} cancelled.")
    return redirect("orders:order_detail", pk=order.pk)


@login_required
def kot_list(request: HttpRequest) -> HttpResponse:
    type_filter = request.GET.get("type", "").strip()
    ticket_type_filter = request.GET.get("ticket_type", "").strip()
    status_filter = request.GET.get("status", "").strip()
    print_status_filter = request.GET.get("print_status", "").strip()
    search = request.GET.get("search", "").strip()
    kots = KOT.objects.select_related("order", "production_unit", "created_by").annotate(
        item_count=Count("items", distinct=True)
    )
    if type_filter:
        kots = kots.filter(type=type_filter)
    if ticket_type_filter:
        kots = kots.filter(ticket_type=ticket_type_filter)
    if status_filter:
        kots = kots.filter(status=status_filter)
    if print_status_filter:
        kots = kots.filter(print_status=print_status_filter)
    if search:
        search_query = Q(kot_number__icontains=search) | Q(order__invoice_number__icontains=search)
        order_number = search.removeprefix("#")
        if order_number.isdigit():
            search_query |= Q(order__order_number=int(order_number))
        kots = kots.filter(search_query)
    kots = kots[:50]
    return render(
        request,
        "backoffice/orders/kot_list.html",
        {
            "kots": kots,
            "type_filter": type_filter,
            "ticket_type_filter": ticket_type_filter,
            "status_filter": status_filter,
            "print_status_filter": print_status_filter,
            "search": search,
            "kot_type_choices": KOT_TYPE_CHOICES,
            "ticket_type_choices": TICKET_TYPE_CHOICES,
            "kot_status_choices": [(SUBMITTED, "Submitted"), ("CANCELLED", "Cancelled")],
            "print_status_choices": KOT_PRINT_STATUS_CHOICES,
        },
    )


@login_required
def kot_detail(request: HttpRequest, pk: int) -> HttpResponse:
    kot = get_object_or_404(
        KOT.objects.select_related("order", "production_unit", "created_by").prefetch_related("items__item"),
        pk=pk,
    )
    return render(request, "backoffice/orders/kot_detail.html", {"kot": kot})


@login_required
@require_POST
def order_return(request: HttpRequest, pk: int) -> HttpResponse:
    """Create a return draft from a submitted order. Manager only."""
    if not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
        messages.error(request, "Only managers can process returns.")
        return redirect("orders:order_detail", pk=pk)
    order = get_object_or_404(Order, pk=pk)
    try:
        return_order = order.make_return()
    except ValidationError as e:
        messages.error(request, str(e.messages[0]) if e.messages else "Return failed.")
        return redirect("orders:order_detail", pk=order.pk)
    messages.success(
        request,
        f"Return draft #{return_order.pk} created from {order.invoice_number}. "
        "Review and submit the return to process refunds.",
    )
    return redirect("orders:order_detail", pk=return_order.pk)

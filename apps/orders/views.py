"""Backoffice views for the orders app — order and KOT management."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import models as django_models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import KOT, Order


@login_required
def order_list(request: HttpRequest) -> HttpResponse:
    search = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()
    order_type_filter = request.GET.get("order_type", "").strip()

    orders = Order.objects.select_related("cashier").all()
    if search:
        orders = orders.filter(
            django_models.Q(invoice_number__icontains=search)
            | django_models.Q(customer_name__icontains=search)
            | django_models.Q(order_number__icontains=search)
        )
    if status_filter:
        orders = orders.filter(status=status_filter)
    if order_type_filter:
        orders = orders.filter(order_type=order_type_filter)
    orders = orders[:50]

    return render(
        request,
        "backoffice/orders/order_list.html",
        {
            "orders": orders,
            "search": search,
            "status_filter": status_filter,
            "order_type_filter": order_type_filter,
        },
    )


@login_required
def order_detail(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(
        Order.objects.select_related("cashier", "opening_entry").prefetch_related(
            "items__item__item_group", "payments__mode_of_payment", "kots__items__item"
        ),
        pk=pk,
    )
    return render(request, "backoffice/orders/order_detail.html", {"order": order})


@login_required
@require_POST
def order_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    if not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
        messages.error(request, "Only managers can cancel orders.")
        return redirect("orders:order_detail", pk=pk)
    order = get_object_or_404(Order, pk=pk)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "A cancel reason is required.")
        return redirect("orders:order_detail", pk=order.pk)
    try:
        order.cancel(reason)
    except ValidationError as e:
        messages.error(request, str(e.messages[0]) if e.messages else "Cancel failed.")
        return redirect("orders:order_detail", pk=order.pk)
    messages.success(request, f"Order {order.invoice_number} cancelled.")
    return redirect("orders:order_detail", pk=order.pk)


@login_required
def kot_list(request: HttpRequest) -> HttpResponse:
    type_filter = request.GET.get("type", "").strip()
    kots = KOT.objects.select_related("order", "production_unit").all()
    if type_filter:
        kots = kots.filter(type=type_filter)
    kots = kots[:50]
    return render(
        request,
        "backoffice/orders/kot_list.html",
        {"kots": kots, "type_filter": type_filter},
    )


@login_required
def kot_detail(request: HttpRequest, pk: int) -> HttpResponse:
    kot = get_object_or_404(
        KOT.objects.select_related("order", "production_unit").prefetch_related("items__item"),
        pk=pk,
    )
    return render(request, "backoffice/orders/kot_detail.html", {"kot": kot})

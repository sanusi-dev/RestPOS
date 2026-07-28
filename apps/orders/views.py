from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models as django_models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import KOT, Order


@login_required
def order_list(request: HttpRequest) -> HttpResponse:
    search = request.GET.get("search", "")
    status_filter = request.GET.get("status", "")
    orders = Order.objects.select_related("branch", "table").all()
    if search:
        orders = orders.filter(
            django_models.Q(invoice_number__icontains=search) | django_models.Q(customer_name__icontains=search)
        )
    if status_filter:
        orders = orders.filter(status=status_filter)
    orders = orders[:50]

    return render(
        request,
        "backoffice/orders/order_list.html",
        {"orders": orders, "search": search, "status_filter": status_filter},
    )


@login_required
def order_detail(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(
        Order.objects.select_related("branch", "table", "room", "pos_profile").prefetch_related(
            "items__item", "payments__mode_of_payment", "taxes", "kots__items__item"
        ),
        pk=pk,
    )
    return render(request, "backoffice/orders/order_detail.html", {"order": order})


@login_required
@require_POST
def order_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    if not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
        return redirect("web:home")
    order = get_object_or_404(Order, pk=pk)
    reason = request.POST.get("reason", "")
    order.cancel(reason)
    messages.success(request, f"Order {order.invoice_number} cancelled.")
    return redirect("orders:order_detail", pk=order.pk)


@login_required
def kot_list(request: HttpRequest) -> HttpResponse:
    kots = KOT.objects.select_related("order", "production_unit").all()[:50]
    return render(request, "backoffice/orders/kot_list.html", {"kots": kots})

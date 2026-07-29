from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.inventory.models import Item
from apps.menu.models import MenuItem
from apps.settings.models import POSProfile

from .models import Order


def _build_context(request):
    profile = POSProfile.objects.select_related("restaurant", "restaurant__branch", "warehouse").first()
    order_id = request.session.get("pos_order_id")
    order = Order.objects.filter(pk=order_id, status="DRAFT").first() if order_id else None
    menu_items = (
        (
            MenuItem.objects.filter(menu=profile.restaurant.active_menu, disabled=False)
            .select_related("item__item_group")
            .order_by("item_name")
        )
        if profile
        else []
    )
    item_groups = {}
    for mi in menu_items:
        gname = mi.item.item_group.name
        item_groups.setdefault(gname, []).append(mi)
    return {"profile": profile, "order": order, "menu_items": menu_items, "item_groups": item_groups}


@login_required
def pos_home(request: HttpRequest) -> HttpResponse:
    profile = POSProfile.objects.first()
    if not profile:
        return render(request, "pos/index.html", {"error": "No POS profile configured."})
    return render(request, "pos/index.html", _build_context(request))


@login_required
def pos_order_new(request: HttpRequest) -> HttpResponse:
    profile = POSProfile.objects.select_related("restaurant", "restaurant__branch").first()
    if not profile:
        return redirect("pos:pos_home")
    order = Order.objects.create(
        order_type=request.POST.get("order_type", "DINE_IN"),
        restaurant=profile.restaurant,
        branch=profile.restaurant.branch,
        pos_profile=profile,
    )
    request.session["pos_order_id"] = order.pk
    return redirect("pos:pos_home")


@login_required
@require_POST
def pos_order_add_item(request: HttpRequest, pk: int) -> HttpResponse:
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status="DRAFT")
        try:
            item_id = int(request.POST.get("item_id", 0))
            qty = int(request.POST.get("qty", 1))
        except ValueError, TypeError:
            return _render_order_panel(request, order)
        if qty <= 0:
            return _render_order_panel(request, order)
        item = get_object_or_404(Item, pk=item_id, is_sales_item=True, disabled=False)
        menu_item = MenuItem.objects.filter(item=item, menu=order.restaurant.active_menu, disabled=False).first()
        if menu_item is None:
            return _render_order_panel(request, order)
        order.add_item(item, qty=qty, customer_index=1, comments="", rate=menu_item.rate)
        order.recalculate_totals()
    return _render_order_panel(request, order)


@login_required
@require_POST
def pos_order_sync(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(Order, pk=pk, status="DRAFT")
    previous = request.session.get(f"order_{pk}_items", [])
    current_state = [
        {"item_id": oi.item_id, "qty": str(oi.qty), "customer_index": oi.customer_index, "comments": oi.comments or ""}
        for oi in order.items.all()
    ]
    order.generate_kots(previous)
    request.session[f"order_{pk}_items"] = current_state
    if order.table and order.order_type == "DINE_IN":
        order.table.occupied = True
        order.table.latest_invoice_time = timezone.now()
        order.table.save(update_fields=["occupied", "latest_invoice_time", "updated_at"])
    return _render_order_panel(request, order)


@login_required
def pos_order_settle(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(Order.objects.prefetch_related("items__item"), pk=pk)
    if request.method == "POST":
        from apps.payments.models import ModeOfPayment

        payment_modes = ModeOfPayment.objects.filter(
            profile_links__pos_profile=order.pos_profile, enabled=True
        ).distinct()
        payments_data = []
        total = Decimal("0")
        for mode in payment_modes:
            amount_str = request.POST.get(f"payment_{mode.pk}", "0")
            if amount_str:
                amt = Decimal(amount_str)
                if amt > 0:
                    payments_data.append({"mode_of_payment": mode.pk, "amount": str(amt)})
                    total += amt
        if not payments_data:
            messages.error(request, "Enter at least one payment amount.")
            return redirect("pos:pos_order_settle", pk=order.pk)
        order.settle(payments_data, cashier=request.user)
        request.session.pop("pos_order_id", None)
        request.session.pop(f"order_{pk}_items", None)
        messages.success(request, f"Order {order.invoice_number} settled.")
        return redirect("pos:pos_home")
    order.calculate_taxes()
    payment_modes = ModeOfPayment.objects.filter(profile_links__pos_profile=order.pos_profile, enabled=True).distinct()
    return render(
        request,
        "pos/settle.html",
        {"order": order, "payment_modes": payment_modes},
    )


@login_required
@require_POST
def pos_order_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(Order, pk=pk)
    order.cancel(request.POST.get("reason", ""))
    request.session.pop("pos_order_id", None)
    request.session.pop(f"order_{pk}_items", None)
    return redirect("pos:pos_home")


def _render_order_panel(request, order):
    order.refresh_from_db()
    ctx = _build_context(request)
    ctx["order"] = order
    return render(request, "pos/index.html", ctx)

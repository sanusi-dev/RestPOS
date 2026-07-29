import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.inventory.models import Item
from apps.menu.models import MenuItem
from apps.payments.models import ModeOfPayment
from apps.settings.models import POSProfile, ProductionUnit, Room, Table

from .models import Order


@login_required
def pos_home(request: HttpRequest) -> HttpResponse:
    """Main POS screen: menu grid on left, order panel on right."""
    profile = POSProfile.objects.select_related("restaurant", "restaurant__branch", "warehouse").first()
    if not profile:
        return render(request, "pos/index.html", {"error": "No POS profile configured."})
    order_id = request.session.get("pos_order_id")
    order = None
    if order_id:
        order = Order.objects.filter(pk=order_id, status="DRAFT").first()
    tables = Table.objects.filter(room__branch=profile.restaurant.branch).select_related("room").order_by("name")
    rooms = Room.objects.filter(branch=profile.restaurant.branch).order_by("name")
    menu_items = (
        MenuItem.objects.filter(menu=profile.restaurant.active_menu, disabled=False)
        .select_related("item")
        .order_by("item_name")
    )
    production_units = ProductionUnit.objects.filter(branch=profile.restaurant.branch)
    item_groups = {}
    for mi in menu_items:
        gname = mi.item.item_group.name
        if gname not in item_groups:
            item_groups[gname] = []
        item_groups[gname].append(mi)
    payment_modes = ModeOfPayment.objects.filter(profile_links__pos_profile=profile, enabled=True).distinct()
    context = {
        "profile": profile,
        "order": order,
        "tables": tables,
        "rooms": rooms,
        "menu_items": menu_items,
        "item_groups": item_groups,
        "production_units": production_units,
        "payment_modes": payment_modes,
    }
    return render(request, "pos/index.html", context)


@login_required
def pos_order_new(request: HttpRequest) -> HttpResponse:
    """Create a new draft order and set it as active in session."""
    table_id = request.POST.get("table_id") or request.GET.get("table_id")
    order_type = request.POST.get("order_type", "DINE_IN")
    profile = POSProfile.objects.select_related("restaurant", "restaurant__branch").first()
    if not profile:
        messages.error(request, "No POS profile configured.")
        return redirect("pos:pos_home")
    order = Order.objects.create(
        order_type=order_type,
        restaurant=profile.restaurant,
        branch=profile.restaurant.branch,
        pos_profile=profile,
        table_id=table_id if table_id else None,
    )
    request.session["pos_order_id"] = order.pk
    return redirect("pos:pos_home")


@login_required
def pos_order_load(request: HttpRequest, pk: int) -> HttpResponse:
    """Load an existing order into the POS session."""
    order = get_object_or_404(Order, pk=pk)
    request.session["pos_order_id"] = order.pk
    return redirect("pos:pos_home")


@login_required
@require_POST
def pos_order_add_item(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(Order, pk=pk, status="DRAFT")
    try:
        item_id = int(request.POST.get("item_id", 0))
        qty = int(request.POST.get("qty", 1))
        customer_index = int(request.POST.get("customer_index", 1))
    except ValueError, TypeError:
        return _cart_error_html(request, order, "Invalid item or quantity.")
    comments = request.POST.get("comments", "")
    item = get_object_or_404(Item, pk=item_id, is_sales_item=True)
    menu_item = MenuItem.objects.filter(item=item, menu=order.restaurant.active_menu, disabled=False).first()
    if menu_item is None:
        return _cart_error_html(request, order, "This item is not on the active menu.")
    rate = menu_item.rate
    order.add_item(item, qty=qty, customer_index=customer_index, comments=comments, rate=rate)
    order.recalculate_totals()
    return _cart_html(request, order)


@login_required
@require_POST
def pos_order_remove_item(request: HttpRequest, pk: int, item_pk: int) -> HttpResponse:
    order = get_object_or_404(Order, pk=pk, status="DRAFT")
    order.remove_item(item_pk)
    return _cart_html(request, order)


@login_required
@require_POST
def pos_order_update_qty(request: HttpRequest, pk: int, item_pk: int) -> HttpResponse:
    order = get_object_or_404(Order, pk=pk, status="DRAFT")
    try:
        new_qty = Decimal(request.POST.get("qty", "0"))
    except ValueError, TypeError:
        return _cart_error_html(request, order, "Invalid quantity.")
    oi = get_object_or_404(order.items, pk=item_pk)
    if new_qty <= 0:
        oi.delete()
    else:
        oi.qty = new_qty
        oi.save()
    order.recalculate_totals()
    return _cart_html(request, order)


@login_required
@require_POST
def pos_order_sync(request: HttpRequest, pk: int) -> HttpResponse:
    """Sync order items and generate KOTs."""
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
    return _cart_html(request, order)


@login_required
def pos_order_settle(request: HttpRequest, pk: int) -> HttpResponse:
    """Payment dialog (GET) and settlement (POST)."""
    order = get_object_or_404(Order.objects.prefetch_related("items__item"), pk=pk)
    if request.method == "POST":
        payments_data = json.loads(request.POST.get("payments", "[]"))
        discount_pct = request.POST.get("discount_percentage")
        discount_on = request.POST.get("discount_on", "GRAND_TOTAL")
        try:
            order.settle(payments_data, cashier=request.user, discount_percentage=discount_pct, discount_on=discount_on)
            request.session.pop("pos_order_id", None)
            request.session.pop(f"order_{pk}_items", None)
            messages.success(request, f"Order {order.invoice_number} settled.")
            return redirect("pos:pos_home")
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect("pos:pos_order_settle", pk=order.pk)
    order.calculate_taxes()
    payment_modes = ModeOfPayment.objects.filter(profile_links__pos_profile=order.pos_profile, enabled=True).distinct()
    return render(
        request,
        "pos/_partials/payment_dialog.html",
        {"order": order, "payment_modes": payment_modes},
    )


@login_required
@require_POST
def pos_order_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    order = get_object_or_404(Order, pk=pk)
    reason = request.POST.get("reason", "")
    order.cancel(reason)
    request.session.pop("pos_order_id", None)
    request.session.pop(f"order_{pk}_items", None)
    messages.success(request, f"Order {order.invoice_number} cancelled.")
    return redirect("pos:pos_home")


@login_required
@require_POST
def pos_customer_card_activate(request: HttpRequest, index: int) -> HttpResponse:
    request.session["pos_active_card"] = index
    order_id = request.session.get("pos_order_id")
    if order_id:
        order = Order.objects.filter(pk=order_id, status="DRAFT").first()
        if order:
            return _customer_cards_html(request, order)
    return HttpResponse("")


@login_required
@require_POST
def pos_guest_count(request: HttpRequest) -> HttpResponse:
    order_id = request.session.get("pos_order_id")
    if not order_id:
        return HttpResponse(status=400)
    count = int(request.POST.get("guest_count", 1))
    Order.objects.filter(pk=order_id, status="DRAFT").update(guest_count=count)
    return _customer_cards_html(request, Order.objects.get(pk=order_id))


def _cart_html(request, order):
    order.refresh_from_db()
    return render(request, "pos/_partials/cart_items.html", {"order": order})


def _cart_error_html(request, order, message):
    order.refresh_from_db()
    return render(request, "pos/_partials/cart_items.html", {"order": order, "error": message})


def _customer_cards_html(request, order):
    return render(request, "pos/_partials/customer_cards.html", {"order": order})

"""POS-facing views for the orders app — the cashier's full-screen workflow."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.inventory.models import Item
from apps.menu.models import MenuItem
from apps.orders.models import DINE_IN, DRAFT, ORDER_TYPE_CHOICES, Order
from apps.payments.models import ModeOfPayment
from apps.settings.models import Restaurant
from apps.staff.models import OpeningPayment, POSOpeningEntry

SESSION_ORDER_KEY = "pos_order_id"
SESSION_CARD_KEY = "pos_active_card"


def _get_open_shift():
    """Return the open POSOpeningEntry, or None. One open shift exists at most."""
    return (
        POSOpeningEntry.objects.select_related("cashier")
        .filter(status=POSOpeningEntry.SUBMITTED, closing_entry__isnull=True)
        .first()
    )


def _get_payment_modes():
    """Return enabled payment modes, ordered with the default first."""
    return ModeOfPayment.objects.filter(enabled=True).order_by("-is_default", "name")


def _get_menu_data(settings):
    """Return menu items grouped by item group name for the POS grid."""
    if not settings or not settings.active_menu_id:
        return []
    return list(
        MenuItem.objects.filter(menu=settings.active_menu, disabled=False)
        .select_related("item", "item__item_group")
        .order_by("item_name")
    )


def _group_menu_items(menu_items):
    """Group menu items by item group name, preserving order."""
    groups = {}
    for mi in menu_items:
        gname = mi.item.item_group.name
        groups.setdefault(gname, []).append(mi)
    return groups


def _get_active_order(request):
    """Return the active draft order from session, or None."""
    order_id = request.session.get(SESSION_ORDER_KEY)
    if not order_id:
        return None
    return Order.objects.filter(pk=order_id, status=DRAFT).first()


def _get_active_card(request, order):
    """Return the active customer card index from session, defaulting to 1."""
    card = request.session.get(SESSION_CARD_KEY, 1)
    if card < 1 or card > order.guest_count:
        return 1
    return card


def _build_order_context(request, order):
    """Build the context dict for the order screen."""
    settings = Restaurant.load()
    menu_items = _get_menu_data(settings)
    return {
        "order": order,
        "menu_items": menu_items,
        "item_groups": _group_menu_items(menu_items),
        "active_card": _get_active_card(request, order),
        "customer_range": range(1, order.guest_count + 1),
        "payment_modes": list(_get_payment_modes()),
        "order_type_choices": ORDER_TYPE_CHOICES,
    }


@login_required
def pos_home(request: HttpRequest) -> HttpResponse:
    """Main POS entry: shift gate, resume draft, or start a new order."""
    settings = Restaurant.load()
    if not settings:
        return render(request, "pos/index.html", {"error": "Restaurant settings are not configured."})

    shift = _get_open_shift()

    if not shift:
        payment_modes = _get_payment_modes()
        return render(request, "pos/index.html", {"no_shift": True, "payment_modes": list(payment_modes)})

    order = _get_active_order(request)
    if order:
        return render(request, "pos/index.html", _build_order_context(request, order))

    open_drafts = (
        Order.objects.filter(status=DRAFT)
        .order_by("-updated_at")
        .only("pk", "invoice_number", "order_number", "order_type", "guest_count", "grand_total", "updated_at")[:20]
    )
    return render(
        request,
        "pos/index.html",
        {
            "shift": shift,
            "show_start": True,
            "order_type_choices": ORDER_TYPE_CHOICES,
            "open_drafts": open_drafts,
        },
    )


@login_required
@require_POST
def pos_open_shift(request: HttpRequest) -> HttpResponse:
    """Create a POSOpeningEntry with opening payments from the POS screen."""
    if Restaurant.load() is None:
        return redirect("pos:pos_home")
    if _get_open_shift():
        messages.error(request, "A shift is already open.")
        return redirect("pos:pos_home")

    payment_modes = _get_payment_modes()
    with transaction.atomic():
        entry = POSOpeningEntry.objects.create(cashier=request.user, status=POSOpeningEntry.SUBMITTED)
        for mode in payment_modes:
            amount_str = request.POST.get(f"opening_{mode.pk}", "0") or "0"
            try:
                amount = Decimal(amount_str)
            except ValueError, TypeError, InvalidOperation:
                amount = Decimal("0")
            if amount > 0:
                OpeningPayment.objects.create(opening_entry=entry, mode_of_payment=mode, opening_amount=amount)
    messages.success(request, "Shift opened successfully.")
    return redirect("pos:pos_home")


@login_required
@require_POST
def pos_order_start(request: HttpRequest) -> HttpResponse:
    """Create a new draft order and open the order screen."""
    if Restaurant.load() is None:
        return redirect("pos:pos_home")
    open_shift = _get_open_shift()
    if not open_shift:
        messages.error(request, "Open a shift before taking orders.")
        return redirect("pos:pos_home")

    order_type = request.POST.get("order_type", DINE_IN)
    valid_types = {c[0] for c in ORDER_TYPE_CHOICES}
    if order_type not in valid_types:
        order_type = DINE_IN

    try:
        guest_count = int(request.POST.get("guest_count", "1"))
    except ValueError, TypeError:
        guest_count = 1
    if guest_count < 1:
        guest_count = 1
    if guest_count > 50:
        guest_count = 50

    order = Order.objects.create(
        order_type=order_type,
        guest_count=guest_count,
        opening_entry=open_shift,
    )
    order.assign_order_number()
    request.session[SESSION_ORDER_KEY] = order.pk
    request.session[SESSION_CARD_KEY] = 1
    return redirect("pos:pos_order_screen", pk=order.pk)


@login_required
def pos_order_screen(request: HttpRequest, pk: int) -> HttpResponse:
    """Render the full POS order screen (menu grid + cart)."""
    order = get_object_or_404(Order.objects.prefetch_related("items__item"), pk=pk, status=DRAFT)
    request.session[SESSION_ORDER_KEY] = order.pk
    return render(request, "pos/index.html", _build_order_context(request, order))


@login_required
@require_POST
def pos_order_update_meta(request: HttpRequest, pk: int) -> HttpResponse:
    """Update order type or guest count on a draft order. Returns the cart partial."""
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status=DRAFT)
        order_type = request.POST.get("order_type")
        if order_type and order_type in {c[0] for c in ORDER_TYPE_CHOICES}:
            order.order_type = order_type
        guest_str = request.POST.get("guest_count")
        if guest_str is not None:
            try:
                guest_count = int(guest_str)
            except ValueError, TypeError:
                guest_count = order.guest_count
            if 1 <= guest_count <= 50:
                order.guest_count = guest_count
                active = request.session.get(SESSION_CARD_KEY, 1)
                if active > guest_count:
                    request.session[SESSION_CARD_KEY] = 1
        order.save(update_fields=["order_type", "guest_count", "updated_at"])

    return render(request, "pos/index.html#cart", _build_order_context(request, order))


@login_required
@require_POST
def pos_order_add_item(request: HttpRequest, pk: int) -> HttpResponse:
    """Add an item to the active customer card. Returns the cart partial."""
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status=DRAFT)
        try:
            item_id = int(request.POST.get("item_id", 0))
            qty = Decimal(str(request.POST.get("qty", "1")))
        except ValueError, TypeError:
            return render(request, "pos/index.html#cart", _build_order_context(request, order))
        if qty <= 0:
            return render(request, "pos/index.html#cart", _build_order_context(request, order))

        item = Item.objects.filter(pk=item_id, is_sales_item=True, disabled=False).first()
        if item is None:
            return render(request, "pos/index.html#cart", _build_order_context(request, order))
        settings = Restaurant.load()
        active_menu = settings.active_menu if settings else None
        menu_item = MenuItem.objects.filter(item=item, menu=active_menu, disabled=False).first()
        if menu_item is None:
            return render(request, "pos/index.html#cart", _build_order_context(request, order))

        active_card = _get_active_card(request, order)
        order.add_item(
            item=item, qty=qty, customer_index=active_card, comments="", rate=menu_item.rate, menu_item=menu_item
        )
        order.recalculate_totals()

    ctx = _build_order_context(request, order)
    return render(request, "pos/index.html#cart", ctx)


@login_required
@require_POST
def pos_order_update_item(request: HttpRequest, pk: int, item_pk: int) -> HttpResponse:
    """Update item quantity or remove it. Returns the cart partial."""
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status=DRAFT)
        action = request.POST.get("action", "update")
        if action == "remove":
            order.remove_item(item_pk)
        else:
            try:
                qty = Decimal(str(request.POST.get("qty", "1")))
            except ValueError, TypeError:
                qty = Decimal("1")
            oi = order.items.filter(pk=item_pk).first()
            if oi:
                if qty <= 0:
                    oi.delete()
                else:
                    oi.qty = qty
                    oi.save()
        order.recalculate_totals()

    ctx = _build_order_context(request, order)
    return render(request, "pos/index.html#cart", ctx)


@login_required
@require_POST
def pos_customer_card_activate(request: HttpRequest, pk: int, idx: int) -> HttpResponse:
    """Set the active customer card in session. Returns cards + cart partials."""
    order = get_object_or_404(Order, pk=pk, status=DRAFT)
    if 1 <= idx <= order.guest_count:
        request.session[SESSION_CARD_KEY] = idx
    ctx = _build_order_context(request, order)
    return render(request, "pos/index.html#cart", ctx)


@login_required
@require_POST
def pos_order_sync(request: HttpRequest, pk: int) -> HttpResponse:
    """Generate KOTs from item diffs."""
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status=DRAFT)
        previous = list(order.items.filter(synced=True).values("item_id", "qty", "customer_index", "comments"))
        previous_state = [
            {
                "item_id": pi["item_id"],
                "qty": str(pi["qty"]),
                "customer_index": pi["customer_index"],
                "comments": pi["comments"] or "",
            }
            for pi in previous
        ]
        kots = order.generate_kots(previous_state)
        order.items.filter(synced=False).update(synced=True)

    ctx = _build_order_context(request, order)
    ctx["sync_success"] = True
    ctx["kot_count"] = len(kots)
    return render(request, "pos/index.html#cart", ctx)


@login_required
def pos_order_settle(request: HttpRequest, pk: int) -> HttpResponse:
    """GET: show payment dialog. POST: process payment and settle."""
    order = get_object_or_404(
        Order.objects.prefetch_related("items", "payments"),
        pk=pk,
        status=DRAFT,
    )

    if request.method == "POST":
        if order.order_type == DINE_IN and not order.invoice_printed:
            messages.error(request, "Print the invoice before settling a dine-in order.")
            return redirect("pos:pos_order_screen", pk=order.pk)

        payments_data = []
        for key, value in request.POST.items():
            if key.startswith("payment_") and value:
                try:
                    amount = Decimal(str(value))
                except ValueError, TypeError:
                    continue
                if amount > 0:
                    mode_pk = key.replace("payment_", "")
                    payments_data.append({"mode_of_payment": mode_pk, "amount": str(amount)})

        if not payments_data:
            messages.error(request, "Enter at least one payment amount.")
            return redirect("pos:pos_order_screen", pk=order.pk)

        try:
            order.settle(payments_data, cashier=request.user)
        except ValidationError as e:
            messages.error(request, str(e.messages[0]) if e.messages else "Settle failed.")
            return redirect("pos:pos_order_screen", pk=order.pk)

        request.session.pop(SESSION_ORDER_KEY, None)
        request.session.pop(SESSION_CARD_KEY, None)
        messages.success(request, f"Order {order.invoice_number} settled.")
        return redirect("pos:pos_home")

    order.recalculate_totals()
    ctx = _build_order_context(request, order)
    ctx["payment_modes"] = list(_get_payment_modes())
    ctx["show_payment"] = True
    return render(request, "pos/index.html#payment_dialog", ctx)


@login_required
@require_POST
def pos_order_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    """Cancel an order with a reason."""
    order = get_object_or_404(Order, pk=pk)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "A cancel reason is required.")
        return redirect("pos:pos_order_screen", pk=order.pk)
    try:
        order.cancel(reason)
    except ValidationError as e:
        messages.error(request, str(e.messages[0]) if e.messages else "Cancel failed.")
        return redirect("pos:pos_order_screen", pk=order.pk)
    request.session.pop(SESSION_ORDER_KEY, None)
    request.session.pop(SESSION_CARD_KEY, None)
    messages.success(request, f"Order {order.invoice_number} cancelled.")
    return redirect("pos:pos_home")


@login_required
@require_POST
def pos_order_print(request: HttpRequest, pk: int) -> HttpResponse:
    """Mark the invoice as printed (required before dine-in settle)."""
    order = get_object_or_404(Order, pk=pk, status=DRAFT)
    order.invoice_printed = True
    order.save(update_fields=["invoice_printed", "updated_at"])
    ctx = _build_order_context(request, order)
    ctx["print_success"] = True
    return render(request, "pos/index.html#cart", ctx)

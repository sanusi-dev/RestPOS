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
from apps.orders.models import (
    CANCEL_REASON_CHOICES,
    DINE_IN,
    DRAFT,
    KOT,
    KOT_PRINT_PENDING,
    KOT_PRINTED,
    ORDER_TYPE_CHOICES,
    SUBMITTED,
    TICKET_BAR,
    TICKET_KITCHEN,
    Order,
)
from apps.payments.models import ModeOfPayment
from apps.settings.models import Restaurant
from apps.staff.models import OpeningPayment, POSOpeningEntry

from . import printing
from .forms import POSOrderCancelForm

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


def _group_items_by_guest(order):
    """Group order items by customer_index with per-guest subtotals."""
    buckets = {}
    for item in order.items.all():
        idx = item.customer_index
        if idx not in buckets:
            buckets[idx] = {"index": idx, "items": [], "subtotal": Decimal("0")}
        buckets[idx]["items"].append(item)
        buckets[idx]["subtotal"] += item.amount

    return [
        buckets.get(idx, {"index": idx, "items": [], "subtotal": Decimal("0")})
        for idx in range(1, order.guest_count + 1)
    ]


def _get_active_card(request, order):
    """Return the active customer card index from session, defaulting to 1."""
    card = request.session.get(SESSION_CARD_KEY, 1)
    if card < 1 or card > order.guest_count:
        return 1
    return card


def _render_cart(request, order, **extra_context):
    """Render the cart fragment with optional action feedback."""
    context = _build_order_context(request, order)
    context.update(extra_context)
    return render(request, "pos/index.html#cart", context)


def _build_order_context(request, order):
    """Build the context dict for the order screen."""
    settings = Restaurant.load()
    active_menu = settings.active_menu if settings else None
    menu_items = [mi for mi in active_menu.items.all() if not mi.disabled] if active_menu else []
    tickets = list(order.kots.select_related("production_unit").filter(status=SUBMITTED))
    tickets_by_type = {}
    for ticket in tickets:
        tickets_by_type.setdefault(ticket.ticket_type, ticket)
    kitchen_ticket = tickets_by_type.get(TICKET_KITCHEN)
    bar_ticket = tickets_by_type.get(TICKET_BAR)
    has_items = order.items.exists()
    return {
        "order": order,
        "menu_items": menu_items,
        "item_groups": _group_menu_items(menu_items),
        "active_card": _get_active_card(request, order),
        "guest_groups": _group_items_by_guest(order),
        "payment_modes": list(_get_payment_modes()),
        "order_type_choices": ORDER_TYPE_CHOICES,
        "cancel_form": POSOrderCancelForm(),
        "cancel_reason_choices": CANCEL_REASON_CHOICES,
        "order_sent": bool(tickets),
        "kitchen_ticket": kitchen_ticket,
        "bar_ticket": bar_ticket,
        "kitchen_ticket_pending": bool(kitchen_ticket and kitchen_ticket.print_status == KOT_PRINT_PENDING),
        "bar_ticket_pending": bool(bar_ticket and bar_ticket.print_status == KOT_PRINT_PENDING),
        "kitchen_ticket_printed": bool(kitchen_ticket and kitchen_ticket.print_status == KOT_PRINTED),
        "bar_ticket_printed": bool(bar_ticket and bar_ticket.print_status == KOT_PRINTED),
        "receipt_printable": has_items,
    }


@login_required
def pos_home(request: HttpRequest) -> HttpResponse:
    """Main POS entry: shift gate or draft orders list."""
    settings = Restaurant.load()
    if not settings:
        return render(request, "pos/index.html", {"error": "Restaurant settings are not configured."})

    shift = _get_open_shift()

    if not shift:
        payment_modes = _get_payment_modes()
        return render(request, "pos/index.html", {"no_shift": True, "payment_modes": list(payment_modes)})

    draft_orders = (
        Order.objects.filter(status=DRAFT)
        .prefetch_related("items")
        .order_by("updated_at")
        .only("pk", "invoice_number", "order_number", "order_type", "guest_count", "grand_total", "updated_at")
    )
    return render(
        request,
        "pos/draft_orders.html",
        {
            "shift": shift,
            "draft_orders": draft_orders,
        },
    )


@login_required
@require_POST
def pos_order_new(request: HttpRequest) -> HttpResponse:
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
def pos_order_screen(request: HttpRequest, pk: int) -> HttpResponse:
    """Render the full POS order screen (menu grid + cart)."""
    order = get_object_or_404(Order.objects.prefetch_related("items__item"), pk=pk, status=DRAFT)
    request.session[SESSION_ORDER_KEY] = order.pk
    return render(request, "pos/index.html", _build_order_context(request, order))


@login_required
@require_POST
def pos_order_update_meta(request: HttpRequest, pk: int) -> HttpResponse:
    """Update order type or guest count on a draft order. Returns the cart partial.

    Accepts either an absolute `guest_count` or a signed `guest_delta` (+1/-1) from the
    stepper. Lowering is refused (with an error banner) when a higher-numbered guest
    still has items, so per-customer data isn't silently reassigned.
    """
    error = None
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status=DRAFT)
        order_type = request.POST.get("order_type")
        if order.kots.exists() and (order_type or "guest_delta" in request.POST or "guest_count" in request.POST):
            error = "This order was sent to the kitchen or bar. Cancel it before making changes."
        else:
            if order_type and order_type in {c[0] for c in ORDER_TYPE_CHOICES}:
                order.order_type = order_type
                order.save(update_fields=["order_type", "updated_at"])

            delta = request.POST.get("guest_delta")
            if delta is not None:
                try:
                    guest_count = order.guest_count + int(delta)
                except ValueError, TypeError:
                    guest_count = order.guest_count
            else:
                try:
                    guest_count = int(request.POST.get("guest_count", order.guest_count))
                except ValueError, TypeError:
                    guest_count = order.guest_count
            guest_count = max(1, min(50, guest_count))
            if guest_count != order.guest_count:
                try:
                    order.change_guest_count(guest_count)
                    active = request.session.get(SESSION_CARD_KEY, 1)
                    if active > order.guest_count:
                        request.session[SESSION_CARD_KEY] = 1
                except ValidationError as e:
                    error = e.messages[0] if e.messages else "Cannot change guest count."

    return _render_cart(request, order, error=error) if error else _render_cart(request, order)


@login_required
@require_POST
def pos_order_add_item(request: HttpRequest, pk: int) -> HttpResponse:
    """Add an item to the active customer card. Returns the cart partial."""
    error = None
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status=DRAFT)
        if order.kots.exists():
            error = "This order was sent to the kitchen or bar. Cancel it before making changes."
        else:
            item_id = 0
            try:
                item_id = int(request.POST.get("item_id", 0))
                qty = Decimal(str(request.POST.get("qty", "1")))
            except ValueError, TypeError, InvalidOperation:
                error = "Invalid item quantity."
                qty = Decimal("0")

            if not error and qty <= 0:
                error = "Quantity must be greater than zero."

            item = Item.objects.filter(pk=item_id, is_sales_item=True, disabled=False).first() if not error else None
            if not error and item is None:
                error = "That menu item is no longer available."

            settings = Restaurant.load()
            active_menu = settings.active_menu if settings else None
            menu_item = (
                MenuItem.objects.filter(item=item, menu=active_menu, disabled=False).first()
                if item and not error
                else None
            )
            if not error and menu_item is None:
                error = "That menu item is not on the active menu."

            if not error and item is not None and menu_item is not None:
                try:
                    active_card = _get_active_card(request, order)
                    order.add_item(
                        item=item,
                        qty=qty,
                        customer_index=active_card,
                        comments="",
                        rate=menu_item.rate,
                        menu_item=menu_item,
                    )
                    order.recalculate_totals()
                except ValidationError as e:
                    error = e.messages[0] if e.messages else "Unable to add that item."

    return _render_cart(request, order, error=error) if error else _render_cart(request, order)


@login_required
@require_POST
def pos_order_update_item(request: HttpRequest, pk: int, item_pk: int) -> HttpResponse:
    """Update item quantity or remove it. Returns the cart partial."""
    error = None
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status=DRAFT)
        if order.kots.exists():
            error = "This order was sent to the kitchen or bar. Cancel it before making changes."
        else:
            action = request.POST.get("action", "update")
            try:
                if action == "remove":
                    order.remove_item(item_pk)
                else:
                    qty = Decimal(str(request.POST.get("qty", "1")))
                    if qty <= 0:
                        order.remove_item(item_pk)
                    else:
                        oi = order.items.filter(pk=item_pk).first()
                        if oi:
                            oi.qty = qty
                            oi.save()
                order.recalculate_totals()
            except ValidationError as e:
                error = e.messages[0] if e.messages else "Invalid item update."
            except ValueError, TypeError, InvalidOperation:
                error = "Invalid item update."

    return _render_cart(request, order, error=error) if error else _render_cart(request, order)


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
    """Create the initial kitchen and bar tickets, then print each independently."""
    try:
        with transaction.atomic():
            order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status=DRAFT)
            kots = order.create_tickets(created_by=request.user)
    except ValidationError as e:
        order = get_object_or_404(Order, pk=pk, status=DRAFT)
        return _render_cart(
            request,
            order,
            error=e.messages[0] if e.messages else "Unable to send the order.",
        )

    print_failures = []
    for kot in kots:
        with transaction.atomic():
            ticket = KOT.objects.select_for_update().get(pk=kot.pk)
            if ticket.status != SUBMITTED:
                continue
            result = printing.print_ticket(ticket)
            if result.success:
                ticket.print_status = KOT_PRINTED
            else:
                print_failures.append(result.ticket_type)
            ticket.save(update_fields=["print_status", "updated_at"])

    return _render_cart(
        request,
        order,
        sync_success=True,
        kot_count=len(kots),
        print_failures=print_failures,
    )


@login_required
@require_POST
def pos_order_clear(request: HttpRequest, pk: int) -> HttpResponse:
    """Empty a draft order before any kitchen or bar ticket has been sent."""
    error = None
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update().prefetch_related("items"), pk=pk, status=DRAFT)
        if order.kots.exists():
            error = "This order was sent to the kitchen or bar. Use Cancel Order instead of Clear."
        else:
            order.items.all().delete()
            order.recalculate_totals()
            if order.invoice_printed:
                order.invoice_printed = False
                order.save(update_fields=["invoice_printed", "updated_at"])

    return _render_cart(request, order, error=error, clear_success=not error)


@login_required
def pos_order_settle(request: HttpRequest, pk: int) -> HttpResponse:
    """GET: show payment dialog. POST: process payment and settle."""
    order = get_object_or_404(
        Order.objects.prefetch_related("items", "payments"),
        pk=pk,
        status=DRAFT,
    )

    if request.method == "POST":
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
    """Cancel a sent draft order with a structured reason."""
    form = POSOrderCancelForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose a cancellation reason before cancelling the order.")
        return redirect("pos:pos_order_screen", pk=pk)
    try:
        with transaction.atomic():
            order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status=DRAFT)
            order.cancel_sent_order(
                reason=form.cleaned_data["cancel_reason"],
                reason_note=form.cleaned_data["cancel_reason_note"],
                cancelled_by=request.user,
            )
    except ValidationError as e:
        messages.error(request, str(e.messages[0]) if e.messages else "Cancel failed.")
        return redirect("pos:pos_order_screen", pk=pk)
    request.session.pop(SESSION_ORDER_KEY, None)
    request.session.pop(SESSION_CARD_KEY, None)
    messages.success(request, f"Order {order.invoice_number} cancelled.")
    return redirect("pos:pos_home")


@login_required
@require_POST
def pos_order_print(request: HttpRequest, pk: int) -> HttpResponse:
    """Print or reprint the receipt for the current draft order."""
    error = None
    feedback = {}
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status=DRAFT)
        if not order.items.exists():
            error = "Add at least one item before printing the receipt."
        else:
            action = "reprint" if order.invoice_printed else "print"
            result = printing.print_receipt(order)
            if result.success:
                if not order.invoice_printed:
                    order.invoice_printed = True
                    order.save(update_fields=["invoice_printed", "updated_at"])
                feedback = {"receipt_print_success": True, "receipt_print_action": action}
            else:
                feedback = {"receipt_print_error": True, "receipt_print_action": action}
    return _render_cart(request, order, error=error, **feedback)


@login_required
@require_POST
def pos_order_ticket_print(request: HttpRequest, pk: int, ticket_type: str, action: str) -> HttpResponse:
    """Retry or reprint one existing kitchen or bar ticket."""
    if ticket_type not in {TICKET_KITCHEN, TICKET_BAR} or action not in {"retry", "reprint"}:
        return HttpResponse(status=404)

    required_status = KOT_PRINT_PENDING if action == "retry" else KOT_PRINTED
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk, status=DRAFT)
        ticket = (
            order.kots.select_for_update()
            .filter(status=SUBMITTED, ticket_type=ticket_type, print_status=required_status)
            .order_by("-created_at")
            .first()
        )
        if ticket is None:
            return _render_cart(request, order, error=f"No {ticket_type} ticket is ready for that action.")

        result = printing.print_ticket(ticket)
        if result.success:
            ticket.print_status = KOT_PRINTED
            feedback = {"ticket_print_success": result.ticket_type, "ticket_print_action": action}
        else:
            ticket.print_status = KOT_PRINT_PENDING
            feedback = {"ticket_print_error": result.ticket_type, "ticket_print_action": action}
        ticket.save(update_fields=["print_status", "updated_at"])
    return _render_cart(request, order, **feedback)


@login_required
def pos_order_history(request: HttpRequest) -> HttpResponse:
    """POS-facing order history with payment-type and date filters."""
    from datetime import date as date_type

    payment_filter = request.GET.get("payment", "").strip()
    date_filter = request.GET.get("date", "").strip()

    orders = Order.objects.select_related("cashier").all()
    if payment_filter == "cash":
        orders = orders.filter(is_paid=True, payments__mode_of_payment__type="CASH")
    elif payment_filter == "electronic":
        orders = orders.filter(is_paid=True, payments__mode_of_payment__type__in=["BANK", "PHONE"])
    elif payment_filter == "refunds":
        orders = orders.filter(is_return=True)
    else:
        orders = orders.exclude(status=SUBMITTED, is_paid=True)
    if date_filter:
        orders = orders.filter(posting_date=date_filter)
    orders = orders.distinct().order_by("-posting_date", "-posting_time")[:50]

    return render(
        request,
        "pos/order_history.html",
        {
            "orders": orders,
            "payment_filter": payment_filter,
            "date_filter": date_filter or str(date_type.today()),
        },
    )

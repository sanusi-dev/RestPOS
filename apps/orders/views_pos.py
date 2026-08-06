"""POS-facing views for the orders app — the cashier's full-screen workflow."""

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.inventory.models import Bin, Item
from apps.menu.models import MenuItem
from apps.orders.models import (
    CANCELLED,
    DINE_IN,
    DISCARDED,
    DRAFT,
    KOT,
    KOT_PRINT_PENDING,
    KOT_PRINTED,
    ORDER_TYPE_CHOICES,
    SUBMITTED,
    TAKE_AWAY,
    TICKET_BAR,
    TICKET_KITCHEN,
    Order,
    OrderPayment,
)
from apps.payments.models import ModeOfPayment
from apps.settings.models import Restaurant
from apps.staff.forms import ClosingPaymentForm, OpeningFloatForm
from apps.staff.models import ClosingPayment, OpeningPayment, POSClosingEntry, POSOpeningEntry

from . import printing
from .forms import POSOrderCancelForm

SESSION_ORDER_KEY = "pos_order_id"
SESSION_CARD_KEY = "pos_active_cards"
CATALOG_FILTER_TARGETS = {"catalog-workspace", "#catalog-workspace"}
ORDER_DETAILS_DRAWER_TARGETS = {"order-details-drawer", "#order-details-drawer"}


def _render_pos_surface(request, template_name, context):
    """Render a full POS page or its HTMX surface partial."""
    if request.htmx:
        template_name = f"{template_name}#surface"
    return render(request, template_name, context)


def _home_or_redirect(request):
    """Return the POS home surface for HTMX or preserve the normal redirect."""
    if request.htmx:
        response = pos_home(request)
        response["HX-Push-Url"] = reverse("pos:pos_home")
        return response
    return redirect("pos:pos_home")


def _get_open_shift(lock=False):
    """Return the open POSOpeningEntry, or None. One open shift exists at most."""
    queryset = (
        POSOpeningEntry.objects.select_related("cashier")
        .filter(status=POSOpeningEntry.SUBMITTED, closing_entry__isnull=True)
        .order_by("period_start_date")
    )
    if lock:
        queryset = queryset.select_for_update()
    return queryset.first()


def _get_payment_modes():
    """Return enabled payment modes, ordered with the default first."""
    return ModeOfPayment.objects.filter(enabled=True).select_related("gl_mapping").order_by("-is_default", "name")


def _get_settle_payment_modes():
    """Return enabled payment modes that can be posted at checkout."""
    return _get_payment_modes().filter(gl_mapping__isnull=False).exclude(gl_mapping__default_account="")


def _get_catalog_filters(request):
    """Read catalog filters from the current request."""
    params = request.GET if request.method == "GET" else request.POST
    query = str(params.get("q", "") or "").strip()
    group = str(params.get("group", "") or "").strip()
    specials = str(params.get("specials", "") or "").lower() in {"1", "true", "on", "yes"}
    return query, group, specials


def _is_catalog_filter_request(request):
    """Return whether an HTMX request targets the replaceable catalog workspace."""
    if not request.htmx:
        return False
    target = request.headers.get("HX-Target")
    if target in CATALOG_FILTER_TARGETS:
        return True
    return target is None and any(parameter in request.GET for parameter in ("q", "group", "specials", "clear_filters"))


def _is_order_details_drawer_request(request):
    """Return whether an HTMX request targets the history detail drawer."""
    return request.htmx and request.headers.get("HX-Target") in ORDER_DETAILS_DRAWER_TARGETS


def _get_kitchen_status(order):
    """Summarize the order's kitchen and bar ticket state."""
    tickets = list(order.kots.all())
    if not tickets:
        return "Not sent"
    if all(ticket.status == CANCELLED or ticket.print_status == "CANCELLED" for ticket in tickets):
        return "Cancelled"
    if any(ticket.status == SUBMITTED and ticket.print_status == KOT_PRINT_PENDING for ticket in tickets):
        return "Pending print"
    return "Sent"


def _group_menu_items(menu_items):
    """Group menu items by item group name, preserving order."""
    groups = {}
    for mi in menu_items:
        gname = mi.item.item_group.name
        groups.setdefault(gname, []).append(mi)
    return groups


def _group_items_by_guest(order, items=None):
    """Group order items by customer_index with per-guest subtotals."""
    buckets = {}
    for item in items if items is not None else order.items.all():
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
    cards = request.session.get(SESSION_CARD_KEY, {})
    card = cards.get(str(order.pk), 1) if isinstance(cards, dict) else 1
    try:
        card = int(card)
    except TypeError, ValueError:
        card = 1
    if card < 1 or card > order.guest_count:
        return 1
    return card


def _render_cart(request, order, **extra_context):
    """Render the cart fragment with optional action feedback."""
    context = _build_order_context(request, order)
    context["catalog_oob"] = True
    context.update(extra_context)
    return render(request, "pos/index.html#cart", context)


def _build_order_context(request, order):
    """Build the context dict for the order screen."""
    catalog_query, catalog_group, catalog_specials = _get_catalog_filters(request)
    settings = Restaurant.load()
    active_menu = (
        settings.active_menu if settings and settings.active_menu_id and settings.active_menu.enabled else None
    )
    setup_error = None
    if settings is None:
        setup_error = "Restaurant settings are not configured."
    elif not settings.active_menu_id or not settings.active_menu or not settings.active_menu.enabled:
        setup_error = "No active menu is configured. Set an enabled menu in restaurant settings."
    all_menu_items = (
        list(
            active_menu.items.select_related("item", "item__item_group")
            .prefetch_related("item__add_ons__add_on_item__menu_items", "item__add_on_for")
            .filter(disabled=False)
        )
        if active_menu
        else []
    )
    group_names = {mi.item.item_group.name for mi in all_menu_items}
    group_lookup = {name.casefold(): name for name in group_names}
    catalog_group = group_lookup.get(catalog_group.casefold(), "") if catalog_group else ""
    normalized_query = catalog_query.casefold()
    menu_items = [
        menu_item
        for menu_item in all_menu_items
        if (not catalog_group or menu_item.item.item_group.name == catalog_group)
        and (not catalog_specials or menu_item.special_dish)
        and (
            not normalized_query
            or normalized_query in menu_item.item_name.casefold()
            or normalized_query in menu_item.item.item_name.casefold()
            or normalized_query in menu_item.item.item_code.casefold()
        )
    ]
    # POS availability is unreserved stock, not physical stock: another open
    # draft must not make the same drink appear sellable a second time.
    drink_item_ids = [mi.item_id for mi in all_menu_items if mi.item.department == "DRINKS"]
    drink_bins = (
        {
            bin_obj.item_id: bin_obj
            for bin_obj in Bin.objects.filter(
                item_id__in=drink_item_ids,
                warehouse=settings.default_warehouse,
            )
        }
        if settings and settings.default_warehouse_id
        else {}
    )
    for menu_item in all_menu_items:
        menu_item.stock_unavailable = False
        menu_item.stock_message = ""
        if menu_item.item.department != "DRINKS":
            continue
        if not menu_item.item.is_stock_item:
            menu_item.stock_unavailable = True
            menu_item.stock_message = "Setup required: mark this drink as a stock item"
            continue
        if not settings or not settings.default_warehouse_id or settings.default_warehouse.disabled:
            menu_item.stock_unavailable = True
            menu_item.stock_message = "Setup required: configure the Bar/POS warehouse"
            continue
        drink_bin = drink_bins.get(menu_item.item_id)
        available_qty = drink_bin.actual_qty - drink_bin.reserved_qty if drink_bin is not None else Decimal("0")
        menu_item.available_qty = available_qty
        if available_qty <= 0:
            menu_item.stock_unavailable = True
            menu_item.stock_message = "Out of stock"
    tickets = list(order.kots.select_related("production_unit").filter(status=SUBMITTED))
    tickets_by_type = {}
    for ticket in tickets:
        tickets_by_type.setdefault(ticket.ticket_type, ticket)
    kitchen_ticket = tickets_by_type.get(TICKET_KITCHEN)
    bar_ticket = tickets_by_type.get(TICKET_BAR)
    items = list(order.items.all())
    has_items = bool(items)
    return {
        "order": order,
        "shift": order.opening_entry,
        "menu_items": menu_items,
        "catalog_item_count": len(all_menu_items),
        "item_groups": _group_menu_items(all_menu_items),
        "special_item_count": sum(1 for item in all_menu_items if item.special_dish),
        "catalog_query": catalog_query,
        "catalog_group": catalog_group,
        "catalog_specials": catalog_specials,
        "catalog_has_filters": bool(catalog_query or catalog_group or catalog_specials),
        "active_card": _get_active_card(request, order),
        "guest_groups": _group_items_by_guest(order, items),
        "payment_modes": list(_get_settle_payment_modes()),
        "order_type_choices": ORDER_TYPE_CHOICES,
        "cancel_form": POSOrderCancelForm(),
        "order_sent": bool(tickets),
        "kitchen_ticket_pending": bool(kitchen_ticket and kitchen_ticket.print_status == KOT_PRINT_PENDING),
        "bar_ticket_pending": bool(bar_ticket and bar_ticket.print_status == KOT_PRINT_PENDING),
        "kitchen_ticket_printed": bool(kitchen_ticket and kitchen_ticket.print_status == KOT_PRINTED),
        "bar_ticket_printed": bool(bar_ticket and bar_ticket.print_status == KOT_PRINTED),
        "can_reprint": request.user.is_manager or request.user.is_admin or request.user.is_superuser,
        "receipt_printable": has_items,
        "setup_error": setup_error,
        "pos_nav": "order",
    }


@login_required
def pos_home(request: HttpRequest) -> HttpResponse:
    """Main POS entry: shift gate or draft orders list."""
    settings = Restaurant.load()
    if not settings:
        return _render_pos_surface(
            request,
            "pos/index.html",
            {"error": "Restaurant settings are not configured.", "pos_nav": "open"},
        )

    shift = _get_open_shift()

    if not shift:
        payment_modes = _get_payment_modes()
        return _render_pos_surface(
            request,
            "pos/index.html",
            {"no_shift": True, "payment_modes": list(payment_modes), "pos_nav": "open"},
        )

    order_filter = request.GET.get("filter", "all").strip()
    order_search = request.GET.get("q", "").strip()
    draft_orders_queryset = (
        Order.objects.filter(status=DRAFT, is_return=False, opening_entry=shift)
        .prefetch_related("items")
        .annotate(has_sent_ticket=Exists(KOT.objects.filter(order_id=OuterRef("pk"), status=SUBMITTED)))
        .order_by("-updated_at")
        .only(
            "pk",
            "invoice_number",
            "order_number",
            "order_type",
            "guest_count",
            "grand_total",
            "arrived_time",
            "updated_at",
            "invoice_printed",
        )
    )
    if order_filter == "draft":
        draft_orders_queryset = draft_orders_queryset.filter(has_sent_ticket=False, invoice_printed=False)
    elif order_filter == "sent":
        draft_orders_queryset = draft_orders_queryset.filter(has_sent_ticket=True)
    if order_search:
        search_query = Q(items__item_name__icontains=order_search)
        if order_search.isdigit():
            search_query |= Q(order_number=int(order_search))
        draft_orders_queryset = draft_orders_queryset.filter(search_query).distinct()
    draft_orders = list(draft_orders_queryset)
    for order in draft_orders:
        items = list(order.items.all())
        order.item_count = len(items)
        order.item_preview = items[:3]
        order.minutes_ago = max(int((timezone.now() - order.updated_at).total_seconds() // 60), 0)
    draft_count = Order.objects.filter(status=DRAFT, is_return=False, opening_entry=shift).count()
    max_open_drafts = settings.max_open_drafts
    return _render_pos_surface(
        request,
        "pos/draft_orders.html",
        {
            "shift": shift,
            "draft_orders": draft_orders,
            "draft_count": draft_count,
            "max_open_drafts": max_open_drafts,
            "drafts_remaining": max(max_open_drafts - draft_count, 0),
            "draft_cap_reached": draft_count >= max_open_drafts,
            "order_filter": order_filter,
            "order_search": order_search,
            "show_order_tabs": True,
            "pos_nav": "open",
        },
    )


@login_required
@require_POST
def pos_order_new(request: HttpRequest) -> HttpResponse:
    """Create a new draft order and open the order screen."""
    if Restaurant.load() is None:
        return _home_or_redirect(request)
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

    with transaction.atomic():
        settings = Restaurant.objects.select_for_update().first()
        open_shift = _get_open_shift(lock=True)
        if not settings or not open_shift:
            messages.error(request, "Open a shift before taking orders.")
            return _home_or_redirect(request)
        draft_count = Order.objects.filter(status=DRAFT, opening_entry=open_shift, is_return=False).count()
        if draft_count >= settings.max_open_drafts:
            messages.error(request, f"The active shift already has {settings.max_open_drafts} open drafts.")
            return _home_or_redirect(request)
        order = Order.objects.create(
            order_type=order_type,
            guest_count=guest_count,
            opening_entry=open_shift,
        )
        order.assign_order_number()
        order.audit("CREATED", actor=request.user, metadata={"order_type": order_type})
    request.session[SESSION_ORDER_KEY] = order.pk
    cards = request.session.get(SESSION_CARD_KEY, {})
    if not isinstance(cards, dict):
        cards = {}
    cards[str(order.pk)] = 1
    request.session[SESSION_CARD_KEY] = cards
    if request.htmx:
        response = _render_pos_surface(request, "pos/index.html", _build_order_context(request, order))
        response["HX-Push-Url"] = reverse("pos:pos_order_screen", kwargs={"pk": order.pk})
        return response
    return redirect("pos:pos_order_screen", pk=order.pk)


@login_required
@require_POST
def pos_open_shift(request: HttpRequest) -> HttpResponse:
    """Create a POSOpeningEntry with opening payments from the POS screen."""
    if Restaurant.load() is None:
        return _home_or_redirect(request)
    form = OpeningFloatForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter valid non-negative opening balances.")
        return _home_or_redirect(request)
    opening_amounts = form.opening_amounts()
    if not opening_amounts:
        messages.error(request, "Configure at least one enabled payment method before opening a shift.")
        return _home_or_redirect(request)

    with transaction.atomic():
        settings = Restaurant.objects.select_for_update().first()
        if not settings or _get_open_shift(lock=True):
            messages.error(request, "A shift is already open.")
            return _home_or_redirect(request)
        entry = POSOpeningEntry.objects.create(
            cashier=request.user, remarks=str(request.POST.get("remarks", "")).strip()
        )
        OpeningPayment.objects.bulk_create(
            [
                OpeningPayment(opening_entry=entry, mode_of_payment=mode, opening_amount=amount)
                for mode, amount in opening_amounts.items()
            ]
        )
        entry.full_clean()
        entry.submit()
    messages.success(request, "Shift opened successfully.")
    if request.htmx:
        return _home_or_redirect(request)
    return redirect("pos:pos_home")


def _closing_form_prefix(mode_of_payment_id):
    # Keyed by payment mode, not ClosingPayment pk: the GET preview builds
    # unsaved rows (pk None), and the POST re-binds the same prefix so the
    # counted amounts survive a re-render on validation errors.
    return f"cp_mop_{mode_of_payment_id}"


def _expected_closing_amounts(open_shift, period_start, period_end):
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


def _ensure_closing_draft(open_shift, cashier):
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


@login_required
@require_http_methods(["GET", "POST"])
def pos_close_shift(request: HttpRequest) -> HttpResponse:
    """Show or submit the active shift's closing reconciliation from the POS.

    GET never creates database rows — it only renders expected amounts for counting.
    POST creates the draft closing entry (if needed) and submits the reconciliation.
    """
    open_shift = _get_open_shift()
    if open_shift is None:
        messages.warning(request, "There is no open shift to close.")
        return _home_or_redirect(request)

    draft_count = Order.objects.filter(opening_entry=open_shift, status=DRAFT, is_return=False).count()
    if draft_count and request.method == "GET":
        return _render_pos_surface(
            request,
            "pos/close_shift.html",
            {
                "draft_count": draft_count,
                "shift": open_shift,
                "show_order_tabs": request.htmx,
                "pos_nav": "close",
            },
        )

    period_start = open_shift.period_start_date
    period_end = timezone.now()
    expected_rows = _expected_closing_amounts(open_shift, period_start, period_end)

    if request.method == "POST":
        with transaction.atomic():
            open_shift = POSOpeningEntry.objects.select_for_update().get(pk=open_shift.pk)
            draft_count = Order.objects.filter(opening_entry=open_shift, status=DRAFT, is_return=False).count()
            if draft_count:
                messages.error(
                    request,
                    f"Close or settle {draft_count} open order{'s' if draft_count != 1 else ''} "
                    "before closing the shift.",
                )
                return _home_or_redirect(request)
            closing = _ensure_closing_draft(open_shift, request.user)
            closing_payments = list(closing.closing_payments.select_related("mode_of_payment"))
            expected_by_mode = {row["mode"].pk: row for row in expected_rows}
            form_data = []
            for payment in closing_payments:
                expected = expected_by_mode.get(payment.mode_of_payment_id)
                if expected is not None:
                    payment.opening_amount = expected["opening_amount"]
                    payment.expected_amount = expected["expected_amount"]
                form_data.append(
                    (
                        payment,
                        ClosingPaymentForm(
                            request.POST,
                            instance=payment,
                            prefix=_closing_form_prefix(payment.mode_of_payment_id),
                        ),
                    )
                )
            if all(form.is_valid() for _payment, form in form_data):
                try:
                    for payment, form in form_data:
                        form.save()
                        payment.save(update_fields=["opening_amount", "expected_amount", "updated_at"])
                    closing.remarks = str(request.POST.get("remarks", "")).strip()
                    closing.period_end_date = timezone.now()
                    closing.save(update_fields=["remarks", "period_end_date", "updated_at"])
                    closing.full_clean()
                    closing.submit()
                except ValidationError as exc:
                    messages.error(request, exc.messages[0] if exc.messages else "Cannot close the shift.")
                else:
                    messages.success(request, "Shift closed successfully.")
                    if request.htmx:
                        return _home_or_redirect(request)
                    return redirect("pos:pos_home")
            # Invalid forms — fall through to re-render with bound forms.
            display_closing = closing
            display_payments = [payment for payment, _form in form_data]
        return _render_pos_surface(
            request,
            "pos/close_shift.html",
            {
                "closing": display_closing,
                "form_data": form_data,
                "total_expected": sum((payment.expected_amount for payment in display_payments), Decimal("0")),
                "draft_count": 0,
                "shift": open_shift,
                "show_order_tabs": request.htmx,
                "pos_nav": "close",
            },
        )

    # GET: render a preview without creating ClosingEntry / ClosingPayment rows.
    existing_draft = POSClosingEntry.objects.filter(
        opening_entry=open_shift,
        status=POSClosingEntry.DRAFT,
    ).first()
    if existing_draft is not None:
        existing_by_mode = {
            cp.mode_of_payment_id: cp for cp in existing_draft.closing_payments.select_related("mode_of_payment").all()
        }
    else:
        existing_by_mode = {}

    form_data = []
    display_payments = []
    for row in expected_rows:
        payment = existing_by_mode.get(row["mode"].pk)
        if payment is None:
            payment = ClosingPayment(
                mode_of_payment=row["mode"],
                opening_amount=row["opening_amount"],
                expected_amount=row["expected_amount"],
                closing_amount=Decimal("0"),
            )
        else:
            payment.opening_amount = row["opening_amount"]
            payment.expected_amount = row["expected_amount"]
        display_payments.append(payment)
        form_data.append(
            (
                payment,
                ClosingPaymentForm(
                    instance=payment if payment.pk else None,
                    initial={"closing_amount": payment.closing_amount if payment.pk else Decimal("0")},
                    prefix=_closing_form_prefix(row["mode"].pk),
                ),
            )
        )

    class _PreviewClosing:
        period_start_date = period_start
        opening_entry = open_shift
        remarks = existing_draft.remarks if existing_draft is not None else ""

    return _render_pos_surface(
        request,
        "pos/close_shift.html",
        {
            "closing": existing_draft if existing_draft is not None else _PreviewClosing(),
            "form_data": form_data,
            "total_expected": sum((payment.expected_amount for payment in display_payments), Decimal("0")),
            "draft_count": 0,
            "shift": open_shift,
            "show_order_tabs": request.htmx,
            "pos_nav": "close",
        },
    )


@login_required
def pos_order_screen(request: HttpRequest, pk: int) -> HttpResponse:
    """Render the full POS order screen (menu grid + cart)."""
    shift = _get_open_shift()
    if shift is None:
        return _home_or_redirect(request)
    order = get_object_or_404(
        Order.objects.prefetch_related("items__item"),
        pk=pk,
        status=DRAFT,
        is_return=False,
        opening_entry=shift,
    )
    request.session[SESSION_ORDER_KEY] = order.pk
    context = _build_order_context(request, order)
    if _is_catalog_filter_request(request):
        return render(request, "pos/index.html#catalog_workspace", context)
    return _render_pos_surface(request, "pos/index.html", context)


@login_required
def pos_order_add_on_dialog(request: HttpRequest, pk: int, item_id: int) -> HttpResponse:
    """Render the optional add-on dialog for a menu item."""
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")
    order = get_object_or_404(Order, pk=pk, status=DRAFT, is_return=False, opening_entry=shift)
    settings = Restaurant.load()
    active_menu = settings.active_menu if settings and settings.active_menu and settings.active_menu.enabled else None
    if active_menu is None:
        return HttpResponse("Active menu is not configured.", status=404)
    menu_item = get_object_or_404(
        MenuItem.objects.select_related("item").prefetch_related("item__add_ons__add_on_item__menu_items"),
        item_id=item_id,
        menu=active_menu,
        disabled=False,
    )
    add_ons = []
    for add_on in menu_item.item.add_ons.all():
        if add_on.add_on_item.disabled or not add_on.add_on_item.is_sales_item:
            continue
        add_on.menu_item = next(
            (
                candidate
                for candidate in add_on.add_on_item.menu_items.all()
                if candidate.menu_id == active_menu.pk and not candidate.disabled
            ),
            None,
        )
        if add_on.menu_item is not None:
            add_ons.append(add_on)
    return render(
        request,
        "pos/partials/catalog/add_on_dialog.html",
        {"order": order, "menu_item": menu_item, "add_ons": add_ons},
    )


@login_required
@require_POST
def pos_order_update_meta(request: HttpRequest, pk: int) -> HttpResponse:
    """Update order type or guest count on a draft order. Returns the cart partial.

    Accepts either an absolute `guest_count` or a signed `guest_delta` (+1/-1) from the
    stepper. Lowering is refused (with an error banner) when a higher-numbered guest
    still has items, so per-customer data isn't silently reassigned.
    """
    error = None
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")
    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update(),
            pk=pk,
            status=DRAFT,
            is_return=False,
            opening_entry=shift,
        )
        order_type = request.POST.get("order_type")
        if order.invoice_printed and (order_type or "guest_delta" in request.POST or "guest_count" in request.POST):
            error = "This receipt has been printed. Draft edits are no longer allowed."
        elif order.kots.exists() and (order_type or "guest_delta" in request.POST or "guest_count" in request.POST):
            # A printed receipt or sent ticket makes the order a committed
            # document: the kitchen may already be cooking these lines.
            error = "This order was sent to the kitchen or bar. Cancel it before making changes."
        else:
            if order_type and order_type not in {c[0] for c in ORDER_TYPE_CHOICES}:
                error = "Choose a valid order type."
            elif order_type:
                order.order_type = order_type
                order.save(update_fields=["order_type", "updated_at"])
                order.audit("ORDER_TYPE_CHANGED", actor=request.user, metadata={"order_type": order_type})

            delta = request.POST.get("guest_delta")
            if error:
                guest_count = order.guest_count
            elif delta is not None:
                try:
                    guest_count = order.guest_count + int(delta)
                except ValueError, TypeError:
                    error = "Guest change must be a valid number."
                    guest_count = order.guest_count
            else:
                try:
                    guest_count = int(request.POST.get("guest_count", order.guest_count))
                except ValueError, TypeError:
                    error = "Guest count must be a valid number."
                    guest_count = order.guest_count
            guest_count = order.guest_count if error else max(1, min(50, guest_count))
            if guest_count != order.guest_count:
                try:
                    order.change_guest_count(guest_count)
                    order.audit("GUEST_COUNT_CHANGED", actor=request.user, metadata={"guest_count": guest_count})
                    active = _get_active_card(request, order)
                    if active > order.guest_count:
                        cards = request.session.get(SESSION_CARD_KEY, {})
                        if isinstance(cards, dict):
                            cards[str(order.pk)] = 1
                            request.session[SESSION_CARD_KEY] = cards
                except ValidationError as e:
                    error = e.messages[0] if e.messages else "Cannot change guest count."

    return _render_cart(request, order, error=error) if error else _render_cart(request, order)


@login_required
@require_POST
def pos_order_add_item(request: HttpRequest, pk: int) -> HttpResponse:
    """Add an item to the active customer card. Returns the cart partial."""
    error = None
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")
    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update(),
            pk=pk,
            status=DRAFT,
            is_return=False,
            opening_entry=shift,
        )
        if order.invoice_printed:
            error = "This receipt has been printed. Draft edits are no longer allowed."
        elif order.kots.exists():
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
            active_menu = (
                settings.active_menu if settings and settings.active_menu and settings.active_menu.enabled else None
            )
            menu_item = (
                MenuItem.objects.filter(item=item, menu=active_menu, disabled=False).first()
                if item and not error
                else None
            )
            if not error and menu_item is None:
                error = "That menu item is not on the active menu."

            comments = str(request.POST.get("comments", "") or "").strip()
            if len(comments) > 200:
                error = "Special instructions must be 200 characters or fewer."

            selected_add_on_ids = []
            for value in request.POST.getlist("add_on_ids"):
                try:
                    selected_add_on_ids.append(int(value))
                except TypeError, ValueError:
                    error = "Choose valid add-ons."
                    break

            add_ons = []
            resolved_add_ons = []
            if not error and item is not None and menu_item is not None and selected_add_on_ids:
                add_ons = list(
                    item.add_ons.select_related("add_on_item").filter(add_on_item_id__in=selected_add_on_ids)
                )
                if len(add_ons) != len(set(selected_add_on_ids)):
                    error = "One or more selected add-ons are not available for this item."
                else:
                    add_on_menu_items = {
                        candidate.item_id: candidate
                        for candidate in MenuItem.objects.filter(
                            item_id__in=[add_on.add_on_item_id for add_on in add_ons],
                            menu=active_menu,
                            disabled=False,
                            item__disabled=False,
                            item__is_sales_item=True,
                        ).select_related("item")
                    }
                    if len(add_on_menu_items) != len(add_ons):
                        error = "One or more selected add-ons are not on the active menu."
                    else:
                        resolved_add_ons = [(add_on, add_on_menu_items[add_on.add_on_item_id]) for add_on in add_ons]

            if not error and item is not None and menu_item is not None:
                try:
                    with transaction.atomic():
                        active_card = _get_active_card(request, order)
                        order.add_item(
                            item=item,
                            qty=qty,
                            customer_index=active_card,
                            comments=comments,
                            rate=menu_item.rate,
                            menu_item=menu_item,
                            item_name=menu_item.item_name,
                        )
                        for add_on, add_on_menu_item in resolved_add_ons:
                            order.add_item(
                                item=add_on.add_on_item,
                                qty=qty,
                                customer_index=active_card,
                                comments="",
                                rate=add_on_menu_item.rate,
                                menu_item=add_on_menu_item,
                                item_name=add_on_menu_item.item_name,
                            )
                        order.recalculate_totals()
                    order.audit(
                        "ITEM_ADDED",
                        actor=request.user,
                        metadata={"item_id": item.pk, "quantity": str(qty), "customer_index": active_card},
                    )
                except ValidationError as e:
                    error = e.messages[0] if e.messages else "Unable to add that item."

    response = _render_cart(request, order, error=error) if error else _render_cart(request, order)
    if not error and request.headers.get("HX-Request"):
        response["HX-Trigger"] = "close-add-on-dialog"
    return response


@login_required
@require_POST
def pos_order_update_item(request: HttpRequest, pk: int, item_pk: int) -> HttpResponse:
    """Update item quantity or remove it. Returns the cart partial."""
    error = None
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")
    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update(),
            pk=pk,
            status=DRAFT,
            is_return=False,
            opening_entry=shift,
        )
        if order.invoice_printed:
            error = "This receipt has been printed. Draft edits are no longer allowed."
        elif order.kots.exists():
            error = "This order was sent to the kitchen or bar. Cancel it before making changes."
        else:
            action = request.POST.get("action", "update")
            try:
                if action == "remove":
                    removed = order.items.filter(pk=item_pk).values("item_id", "qty").first()
                    order.remove_item(item_pk)
                    if removed:
                        order.audit(
                            "ITEM_REMOVED",
                            actor=request.user,
                            metadata={"item_id": removed["item_id"], "quantity": str(removed["qty"])},
                        )
                elif action in {"increment", "decrement"}:
                    oi = order.items.filter(pk=item_pk).first()
                    if oi is None:
                        error = "That order line no longer exists."
                    else:
                        new_qty = oi.qty + (Decimal("1") if action == "increment" else Decimal("-1"))
                        order.update_item_quantity(item_pk, new_qty)
                        order.audit(
                            "ITEM_QUANTITY_CHANGED",
                            actor=request.user,
                            metadata={"item_id": item_pk, "quantity": str(new_qty)},
                        )
                else:
                    qty = Decimal(str(request.POST.get("qty", "1")))
                    if qty <= 0:
                        order.remove_item(item_pk)
                    else:
                        oi = order.items.filter(pk=item_pk).first()
                        if oi:
                            order.update_item_quantity(item_pk, qty)
                            order.audit(
                                "ITEM_QUANTITY_CHANGED",
                                actor=request.user,
                                metadata={"item_id": item_pk, "quantity": str(qty)},
                            )
                order.recalculate_totals()
            except ValidationError as e:
                error = e.messages[0] if e.messages else "Invalid item update."
            except ValueError, TypeError, InvalidOperation:
                error = "Invalid item update."

    return _render_cart(request, order, error=error) if error else _render_cart(request, order)


@login_required
@require_POST
def pos_customer_card_activate(request: HttpRequest, pk: int, idx: int) -> HttpResponse:
    """Set the active customer card in session. Returns the cart (with catalog OOB)."""
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")
    order = get_object_or_404(Order, pk=pk, status=DRAFT, is_return=False, opening_entry=shift)
    if 1 <= idx <= order.guest_count:
        cards = request.session.get(SESSION_CARD_KEY, {})
        if not isinstance(cards, dict):
            cards = {}
        cards[str(order.pk)] = idx
        request.session[SESSION_CARD_KEY] = cards
    return _render_cart(request, order)


@login_required
@require_POST
def pos_order_sync(request: HttpRequest, pk: int) -> HttpResponse:
    """Create the initial kitchen and bar tickets, then print each independently."""
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")
    try:
        with transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update(),
                pk=pk,
                status=DRAFT,
                is_return=False,
                opening_entry=shift,
            )
            kots = order.create_tickets(created_by=request.user)
    except ValidationError as e:
        order = get_object_or_404(Order, pk=pk, status=DRAFT, is_return=False, opening_entry=shift)
        return _render_cart(
            request,
            order,
            error=e.messages[0] if e.messages else "Unable to send the order.",
        )

    # Print each ticket individually so one printer failure doesn't block
    # the other station; failures are surfaced for a manual retry.
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

    if not print_failures:
        messages.success(request, f"Sent {len(kots)} ticket{'s' if len(kots) != 1 else ''} to kitchen & bar.")

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
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")
    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update().prefetch_related("items"),
            pk=pk,
            status=DRAFT,
            is_return=False,
            opening_entry=shift,
        )
        if order.invoice_printed:
            error = "This receipt has been printed. Draft edits are no longer allowed."
        elif order.kots.exists():
            error = "This order was sent to the kitchen or bar. Use Cancel Order instead of Clear."
        else:
            order.clear_items()
            order.audit("ITEMS_CLEARED", actor=request.user)
            messages.success(request, "Order cleared.")

    return _render_cart(request, order, error=error)


@login_required
@require_http_methods(["GET", "POST"])
def pos_order_settle(request: HttpRequest, pk: int) -> HttpResponse:
    """GET: show payment dialog. POST: process payment and settle."""
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")
    order = get_object_or_404(
        Order.objects.prefetch_related("items", "payments"),
        pk=pk,
        status=DRAFT,
        is_return=False,
        opening_entry=shift,
    )

    if request.method == "POST":
        payments_data = []
        for key, value in request.POST.items():
            mode_pk = key.removeprefix("payment_") if key.startswith("payment_") else ""
            if mode_pk.isdigit() and str(value).strip() != "":
                payments_data.append(
                    {
                        "mode_of_payment": mode_pk,
                        "amount": value,
                        "reference_no": request.POST.get(f"reference_{mode_pk}", ""),
                    }
                )

        if not payments_data:
            messages.error(request, "Enter at least one payment amount.")
            return redirect("pos:pos_order_screen", pk=order.pk)

        try:
            order.settle(payments_data, cashier=request.user, opening_entry=shift)
        except ValidationError as e:
            messages.error(request, str(e.messages[0]) if e.messages else "Settle failed.")
            return redirect("pos:pos_order_screen", pk=order.pk)

        request.session.pop(SESSION_ORDER_KEY, None)
        cards = request.session.get(SESSION_CARD_KEY, {})
        if isinstance(cards, dict):
            cards.pop(str(order.pk), None)
            request.session[SESSION_CARD_KEY] = cards
        messages.success(request, f"Order {order.invoice_number} settled.")
        return redirect("pos:pos_home")

    ctx = _build_order_context(request, order)
    ctx["payment_modes"] = list(_get_settle_payment_modes())
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
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")
    cancellation_kots = []
    try:
        with transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update(),
                pk=pk,
                status=DRAFT,
                is_return=False,
                opening_entry=shift,
            )
            cancellation_kots = order.cancel_sent_order(
                reason=form.cleaned_data["cancel_reason"],
                reason_note=form.cleaned_data["cancel_reason_note"],
                cancelled_by=request.user,
            )
    except ValidationError as e:
        messages.error(request, str(e.messages[0]) if e.messages else "Cancel failed.")
        return redirect("pos:pos_order_screen", pk=pk)

    print_failures = []
    for cancellation_kot in cancellation_kots:
        result = printing.print_ticket(cancellation_kot)
        with transaction.atomic():
            ticket = KOT.objects.select_for_update().get(pk=cancellation_kot.pk)
            if result.success:
                ticket.print_status = KOT_PRINTED
            else:
                ticket.print_status = KOT_PRINT_PENDING
                print_failures.append(result.ticket_type)
            ticket.save(update_fields=["print_status", "updated_at"])

    request.session.pop(SESSION_ORDER_KEY, None)
    cards = request.session.get(SESSION_CARD_KEY, {})
    if isinstance(cards, dict):
        cards.pop(str(order.pk), None)
        request.session[SESSION_CARD_KEY] = cards
    if print_failures:
        failed = ", ".join(sorted(set(print_failures)))
        messages.warning(
            request,
            f"Order {order.invoice_number} cancelled, but the {failed} cancellation ticket "
            "failed to print. Retry it from order history.",
        )
    else:
        messages.success(request, f"Order {order.invoice_number} cancelled.")
    return redirect("pos:pos_home")


@login_required
@require_POST
def pos_order_discard(request: HttpRequest, pk: int) -> HttpResponse:
    """Discard an empty draft order that never got items, a receipt, or a ticket."""
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")
    try:
        with transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update(),
                pk=pk,
                status=DRAFT,
                is_return=False,
                opening_entry=shift,
            )
            order.discard(discarded_by=request.user)
    except ValidationError as e:
        messages.error(request, str(e.messages[0]) if e.messages else "Discard failed.")
        return redirect("pos:pos_order_screen", pk=pk)
    request.session.pop(SESSION_ORDER_KEY, None)
    cards = request.session.get(SESSION_CARD_KEY, {})
    if isinstance(cards, dict):
        cards.pop(str(order.pk), None)
        request.session[SESSION_CARD_KEY] = cards
    messages.success(request, f"Order {order.invoice_number} discarded.")
    return redirect("pos:pos_home")


@login_required
@require_POST
def pos_order_print(request: HttpRequest, pk: int) -> HttpResponse:
    """Print or reprint the receipt for the current draft order.

    Claim the printed state in the database first, then print after commit so a
    successful physical print cannot leave the order marked unprinted.
    """
    error = None
    feedback = {}
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")

    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update(),
            pk=pk,
            status=DRAFT,
            is_return=False,
            opening_entry=shift,
        )
        if not order.items.exists():
            error = "Add at least one item before printing the receipt."
            return _render_cart(request, order, error=error)

        action = "reprint" if order.invoice_printed else "print"
        if not order.invoice_printed:
            order.invoice_printed = True
            order.invoice_printed_at = timezone.now()
            order.invoice_printed_by = request.user
            order.save(
                update_fields=[
                    "invoice_printed",
                    "invoice_printed_at",
                    "invoice_printed_by",
                    "updated_at",
                ]
            )
            order.audit("RECEIPT_PRINTED", actor=request.user)

    # Print outside the transaction: the printed state was claimed in the
    # DB first, so a failed physical print still leaves the order marked
    # printed rather than risking a duplicate print on retry.
    result = printing.print_receipt(order)
    if result.success:
        messages.success(
            request,
            f"Receipt {'reprinted' if action == 'reprint' else 'printed'} successfully.",
        )
    else:
        feedback = {"receipt_print_error": True, "receipt_print_action": action}
    return _render_cart(request, order, error=error, **feedback)


@login_required
@require_POST
def pos_order_ticket_print(request: HttpRequest, pk: int, ticket_type: str, action: str) -> HttpResponse:
    """Retry or reprint one kitchen/bar ticket, including cancellation tickets."""
    if ticket_type not in {TICKET_KITCHEN, TICKET_BAR} or action not in {"retry", "reprint"}:
        return HttpResponse(status=404)
    if action == "reprint" and not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
        return HttpResponse(status=403)
    shift = _get_open_shift()
    if shift is None:
        return redirect("pos:pos_home")

    feedback = {}
    required_status = KOT_PRINT_PENDING if action == "retry" else KOT_PRINTED
    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update(),
            pk=pk,
            status__in=[DRAFT, CANCELLED],
            is_return=False,
            opening_entry=shift,
        )
        # Cancellation tickets remain SUBMITTED with print_status PENDING after a failed print.
        ticket = (
            order.kots.select_for_update()
            .filter(ticket_type=ticket_type, print_status=required_status, status=SUBMITTED)
            .order_by("-created_at")
            .first()
        )
        if ticket is None:
            if order.status == DRAFT:
                return _render_cart(request, order, error=f"No {ticket_type} ticket is ready for that action.")
            messages.error(request, f"No {ticket_type} cancellation ticket is ready for that action.")
            return redirect("pos:pos_order_history_detail", pk=order.pk)
        ticket_pk = ticket.pk

    result = printing.print_ticket(KOT.objects.get(pk=ticket_pk))
    with transaction.atomic():
        ticket = KOT.objects.select_for_update().get(pk=ticket_pk)
        order = Order.objects.get(pk=pk)
        if result.success:
            ticket.print_status = KOT_PRINTED
            messages.success(
                request,
                f"{result.ticket_type.title()} ticket {'reprinted' if action == 'reprint' else 'retried'}.",
            )
        else:
            ticket.print_status = KOT_PRINT_PENDING
            feedback = {"ticket_print_error": result.ticket_type, "ticket_print_action": action}
            if order.status != DRAFT:
                messages.error(
                    request,
                    f"{result.ticket_type.title()} cancellation ticket failed to print. Try again.",
                )
        ticket.save(update_fields=["print_status", "updated_at"])

    if order.status == DRAFT:
        return _render_cart(request, order, **feedback)
    return redirect("pos:pos_order_history_detail", pk=order.pk)


@login_required
def pos_order_history(request: HttpRequest) -> HttpResponse:
    """Show cashier-safe historical orders for a selected date.

    Defaults to today's paid sales; cashiers without full-history access
    are restricted to that view (and payment-method filtering).
    """
    from datetime import date as date_type

    payment_filter = request.GET.get("payment", "").strip()
    status_filter = request.GET.get("status", "sales").strip()
    order_type_filter = request.GET.get("order_type", "").strip()
    search = request.GET.get("q", "").strip()
    if "date" not in request.GET:
        parsed_date = timezone.localdate()
        date_filter = str(parsed_date)
    else:
        date_filter = request.GET.get("date", "").strip()
        if date_filter:
            try:
                parsed_date = date_type.fromisoformat(date_filter)
            except ValueError:
                parsed_date = timezone.localdate()
                date_filter = str(parsed_date)
        else:
            parsed_date = None

    restaurant = Restaurant.load()
    is_manager = request.user.is_manager or request.user.is_admin or request.user.is_superuser
    allow_full_history = bool(restaurant and restaurant.pos_allow_full_history) or is_manager
    manager_only_filters = {"all", "returns", "cancelled", "discarded"}
    if status_filter in manager_only_filters and not allow_full_history:
        status_filter = "sales"

    orders = Order.objects.select_related("cashier").prefetch_related("payments__mode_of_payment", "items")
    if search:
        search_query = Q(invoice_number__icontains=search)
        if search.isdigit():
            search_query |= Q(order_number=int(search))
        orders = orders.filter(search_query)
    if status_filter == "all":
        orders = orders.filter(
            Q(status=SUBMITTED, is_return=False, is_paid=True)
            | Q(status=SUBMITTED, is_return=True)
            | Q(status=CANCELLED, is_return=False)
            | Q(status=DISCARDED, is_return=False)
        )
    elif status_filter == "returns":
        orders = orders.filter(status=SUBMITTED, is_return=True)
    elif status_filter == "cancelled":
        orders = orders.filter(status=CANCELLED, is_return=False)
    elif status_filter == "discarded":
        orders = orders.filter(status=DISCARDED, is_return=False)
    else:
        status_filter = "sales"
        orders = orders.filter(status=SUBMITTED, is_paid=True, is_return=False)
    if status_filter == "sales" and payment_filter == "cash":
        orders = orders.filter(
            status=SUBMITTED,
            is_return=False,
            is_paid=True,
            payments__mode_of_payment__type="CASH",
        )
    elif status_filter == "sales" and payment_filter == "electronic":
        orders = orders.filter(
            status=SUBMITTED,
            is_return=False,
            is_paid=True,
            payments__mode_of_payment__type__in=["BANK", "PHONE"],
        )
    if order_type_filter in {DINE_IN, TAKE_AWAY}:
        orders = orders.filter(order_type=order_type_filter)
    if parsed_date is not None:
        orders = orders.filter(posting_date=parsed_date)
    orders = orders.distinct().order_by("-posting_date", "-posting_time")
    paginator = Paginator(orders, 50)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)
    open_shift = _get_open_shift()
    return _render_pos_surface(
        request,
        "pos/order_history.html",
        {
            "orders": page_obj,
            "page_obj": page_obj,
            "paginator": paginator,
            "payment_filter": payment_filter,
            "status_filter": status_filter,
            "order_type_filter": order_type_filter,
            "search": search,
            "date_filter": date_filter,
            "allow_full_history": allow_full_history,
            "shift": open_shift,
            "draft_count": (
                Order.objects.filter(status=DRAFT, is_return=False, opening_entry=open_shift).count()
                if open_shift
                else 0
            ),
            "show_order_tabs": True,
            "pos_nav": "history",
        },
    )


@login_required
def pos_order_history_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Show a read-only cashier view of a historical order."""
    order = get_object_or_404(
        Order.objects.select_related("cashier", "opening_entry", "stock_warehouse").prefetch_related(
            "items__item", "payments__mode_of_payment", "kots__production_unit"
        ),
        pk=pk,
        status__in=[SUBMITTED, CANCELLED, DISCARDED],
    )
    open_shift = _get_open_shift()
    context = {
        "order": order,
        "draft_count": (
            Order.objects.filter(status=DRAFT, is_return=False, opening_entry=open_shift).count() if open_shift else 0
        ),
        "show_order_tabs": request.htmx,
        "pos_nav": "history",
        "kitchen_status": _get_kitchen_status(order),
        # GET opens the drawer with a slide-in; POST re-renders (print) stay put.
        "drawer_animate": request.method == "GET",
    }
    if _is_order_details_drawer_request(request):
        return render(request, "pos/order_history_detail.html#drawer", context)
    return _render_pos_surface(request, "pos/order_history_detail.html", context)


@login_required
@require_POST
def pos_order_history_print(request: HttpRequest, pk: int) -> HttpResponse:
    """Reprint a submitted historical receipt without editing it."""
    order = get_object_or_404(Order, pk=pk, status=SUBMITTED)
    result = printing.print_receipt(order)
    if result.success:
        messages.success(request, "Receipt reprinted successfully.")
    else:
        messages.error(request, "Receipt could not be printed.")
    if request.htmx:
        response = pos_order_history_detail(request, pk=order.pk)
        if not _is_order_details_drawer_request(request):
            response["HX-Push-Url"] = reverse("pos:pos_order_history_detail", kwargs={"pk": order.pk})
        return response
    return redirect("pos:pos_order_history_detail", pk=order.pk)

import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    ClosingPaymentForm,
    OpeningFloatForm,
)
from .models import ClosingPayment, OpeningPayment, POSClosingEntry, POSOpeningEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@login_required
def staff_dashboard(request: HttpRequest) -> HttpResponse:
    """Current shift state and recent closes."""
    open_entry = (
        POSOpeningEntry.objects.filter(
            status=POSOpeningEntry.SUBMITTED,
            closing_entry__isnull=True,
        )
        .select_related("cashier")
        .order_by("-period_start_date")
        .first()
    )
    recent_closes = POSClosingEntry.objects.select_related("cashier", "opening_entry").order_by("-period_end_date")[:5]
    return render(
        request,
        "backoffice/staff/dashboard.html",
        {"open_entry": open_entry, "recent_closes": recent_closes},
    )


# ---------------------------------------------------------------------------
# POSOpeningEntry
# ---------------------------------------------------------------------------


@login_required
def opening_entry_list(request: HttpRequest) -> HttpResponse:
    entries = POSOpeningEntry.objects.select_related("cashier", "closing_entry").order_by("-period_start_date")
    return render(request, "backoffice/staff/opening_entry_list.html", {"entries": entries})


@login_required
def opening_entry_create(request: HttpRequest) -> HttpResponse:
    # NOTE: must use the explicit `if request.method == "POST"` test rather
    # than `request.POST or None`, because an empty QueryDict is falsy — so a
    # POST with no form fields (the no-modes edge case, or a client that
    # omits all inputs) would be treated as a GET and `_save_opening_entry`
    # would never run.
    form = OpeningFloatForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        entry = _save_opening_entry(form, request.user, instance=None)
        if entry is not None:
            messages.success(request, f"Opening entry #{entry.pk} created.")
            return redirect("staff:opening_entry_detail", pk=entry.pk)
    return render(
        request,
        "backoffice/staff/opening_entry_form.html",
        {"form": form, "is_create": True},
    )


@login_required
def opening_entry_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Opening-entry detail page — also handles inline save for DRAFT rows.

    Symmetric with `closing_entry_detail`:
    - GET: render the detail page. For DRAFT, the opening-float table is an
      inline-editable form (one input per `OpeningPayment`, posting back
      here). For SUBMITTED/CANCELLED, it's read-only.
    - POST: re-use `_save_opening_entry` to persist the edited amounts for
      DRAFT entries only, then redirect back here (PRG pattern).
    """
    entry = get_object_or_404(
        POSOpeningEntry.objects.select_related("cashier", "closing_entry"),
        pk=pk,
    )
    opening_payments = list(entry.opening_payments.select_related("mode_of_payment"))
    closing_payments = None
    if entry.closing_entry_id:
        closing_payments = entry.closing_entry.closing_payments.select_related("mode_of_payment")

    if request.method == "POST":
        if entry.status != POSOpeningEntry.DRAFT:
            messages.error(request, "Only draft opening entries can be edited.")
            return redirect("staff:opening_entry_detail", pk=entry.pk)
        form = OpeningFloatForm(request.POST)
        if form.is_valid():
            updated = _save_opening_entry(form, request.user, instance=entry)
            if updated is not None:
                messages.success(request, f"Opening entry #{entry.pk} updated.")
                return redirect("staff:opening_entry_detail", pk=entry.pk)
        # Re-render with the bound form (errors surfaced on each field).
        return render(
            request,
            "backoffice/staff/opening_entry_detail.html",
            {
                "entry": entry,
                "opening_payments": opening_payments,
                "closing_payments": closing_payments,
                "form": form,
            },
        )

    # GET — build an unbound form pre-filled with existing draft amounts so
    # the inline table renders the current values.
    if entry.status == POSOpeningEntry.DRAFT:
        initial = _entry_to_initial(entry)
        form = OpeningFloatForm(initial=initial)
    else:
        form = None
    return render(
        request,
        "backoffice/staff/opening_entry_detail.html",
        {
            "entry": entry,
            "opening_payments": opening_payments,
            "closing_payments": closing_payments,
            "form": form,
        },
    )


# ---------------------------------------------------------------------------
# Opening-entry helpers (all-methods form — see apps/staff/forms.py docstring)
# ---------------------------------------------------------------------------


def _entry_to_initial(entry: POSOpeningEntry) -> dict:
    """Build form-initial data from an existing draft's OpeningPayment rows."""
    initial = {}
    for op in entry.opening_payments.select_related("mode_of_payment"):
        initial[OpeningFloatForm._field_name_for(op.mode_of_payment)] = str(op.opening_amount)
    return initial


def _save_opening_entry(form: OpeningFloatForm, cashier, instance: POSOpeningEntry | None) -> POSOpeningEntry | None:
    """Persist a POSOpeningEntry and its OpeningPayment rows from a bound form."""
    opening_amounts = form.opening_amounts()
    if not opening_amounts:
        form.add_error(
            None,
            "No active payment methods found. Ask a manager to add at least "
            "one payment method in Settings before opening a shift.",
        )
        return None

    with transaction.atomic():
        entry = instance or POSOpeningEntry(cashier=cashier)
        entry.cashier = cashier
        entry.save()
        # Replace the existing child rows on edit; this also clears stale
        # rows for modes that have since been disabled.
        if instance is not None:
            entry.opening_payments.all().delete()
        rows = [
            OpeningPayment(
                opening_entry=entry,
                mode_of_payment=mode,
                opening_amount=amount,
            )
            for mode, amount in opening_amounts.items()
        ]
        OpeningPayment.objects.bulk_create(rows)
        return entry


@login_required
@require_POST
def opening_entry_submit(request: HttpRequest, pk: int) -> HttpResponse:
    entry = get_object_or_404(POSOpeningEntry, pk=pk)
    if entry.status != POSOpeningEntry.DRAFT:
        messages.error(request, "This opening entry is no longer in draft.")
        return redirect("staff:opening_entry_detail", pk=entry.pk)
    # `clean()` enforces "one Open shift" and `submit()` re-checks inside
    # `select_for_update` (race-safe). The legacy "confirm_empty" branch was
    # removed because `_save_opening_entry` now always seeds one row per
    # active `ModeOfPayment` — a draft with no rows only exists if no modes
    # are configured, in which case the create form blocks it at the form
    # level (no `OpeningPayment` rows can ever be missing on a draft).
    try:
        entry.full_clean()
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect("staff:opening_entry_detail", pk=entry.pk)
    except Exception:
        logger.exception("Opening entry submission failed", extra={"opening_entry_id": entry.pk})
        messages.error(request, "Cannot submit the opening entry.")
        return redirect("staff:opening_entry_detail", pk=entry.pk)
    entry.submit()
    messages.success(request, f"Shift opened. Entry #{entry.pk} is now Open.")
    return redirect("staff:opening_entry_detail", pk=entry.pk)


@login_required
@require_POST
def opening_entry_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    entry = get_object_or_404(POSOpeningEntry, pk=pk)
    if entry.closing_entry_id is not None:
        messages.error(
            request,
            "Cannot cancel a shift that has already been closed. Cancel the closing entry instead.",
        )
        return redirect("staff:opening_entry_detail", pk=entry.pk)
    try:
        entry.cancel(by_user=request.user)
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect("staff:opening_entry_detail", pk=entry.pk)
    except Exception:
        logger.exception("Opening entry cancellation failed", extra={"opening_entry_id": entry.pk})
        messages.error(request, "Cannot cancel the opening entry.")
        return redirect("staff:opening_entry_detail", pk=entry.pk)
    messages.success(request, f"Opening entry #{entry.pk} cancelled.")
    return redirect("staff:opening_entry_list")


# ---------------------------------------------------------------------------
# POSClosingEntry
# ---------------------------------------------------------------------------


@login_required
def closing_entry_list(request: HttpRequest) -> HttpResponse:
    entries = POSClosingEntry.objects.select_related("cashier", "opening_entry").order_by("-period_end_date")
    return render(request, "backoffice/staff/closing_entry_list.html", {"entries": entries})


@login_required
def closing_entry_create(request: HttpRequest) -> HttpResponse:
    """Auto-create (or reuse) a DRAFT closing entry for the single Open shift.

    RestPOS enforces a single Open shift (see `POSOpeningEntry.clean()`).
    With that constraint, a dropdown of open shifts to close is pure
    friction — there is at most one. This endpoint implements the
    Lightspeed / Dynamics 365 / StoreHub pattern: clicking "Close Shift"
    immediately starts the close flow against *the* Open shift, no
    selection step.

    Flow:
    1. Find the single Open shift.
    2. If none exists → message + redirect back to dashboard (the dashboard
       "Close shift" button is hidden in this case, so this path is the
       defensive fallback).
    3. If a DRAFT `POSClosingEntry` already exists for that opening →
       redirect to its detail page (prevents double-click / refresh from
       creating duplicate drafts).
    4. Otherwise, atomically create a new DRAFT closing entry + seed one
       `ClosingPayment` row per `OpeningPayment` (mirrors ERPNext's
       `pos_closing_entry.js` `set_opening_amounts` trigger), and redirect
       to the detail page.

    `select_for_update()` on the open shift serialises concurrent "Close
    Shift" clicks so a double-click on the dashboard button cannot race
    into two drafts.
    """
    # Find the single Open shift first (no transaction needed for a read).
    open_entry = (
        POSOpeningEntry.objects.filter(status=POSOpeningEntry.SUBMITTED, closing_entry__isnull=True)
        .select_related("cashier")
        .order_by("period_start_date")
        .first()
    )
    if open_entry is None:
        messages.warning(request, "There is no open shift to close. Open a shift first.")
        return redirect("staff:dashboard")

    with transaction.atomic():
        # Lock the open shift row so two concurrent "Close Shift" clicks
        # cannot both pass the duplicate-draft check below. PostgreSQL's
        # `select_for_update` holds the lock until COMMIT.
        open_entry = POSOpeningEntry.objects.select_for_update().select_related("cashier").get(pk=open_entry.pk)
        existing_draft = POSClosingEntry.objects.filter(opening_entry=open_entry, status=POSClosingEntry.DRAFT).first()
        if existing_draft is not None:
            return redirect("staff:closing_entry_detail", pk=existing_draft.pk)

        closing = POSClosingEntry.objects.create(
            opening_entry=open_entry,
            cashier=request.user,
        )
        rows = [
            ClosingPayment(
                closing_entry=closing,
                mode_of_payment=op.mode_of_payment,
                opening_amount=op.opening_amount,
                expected_amount=op.opening_amount,
                closing_amount=Decimal("0"),
                difference=Decimal("0"),
            )
            for op in open_entry.opening_payments.all()
        ]
        ClosingPayment.objects.bulk_create(rows)
    messages.success(
        request,
        f"Closing entry #{closing.pk} started for the open shift. "
        "Count the drawer and enter the closing amounts below.",
    )
    return redirect("staff:closing_entry_detail", pk=closing.pk)


@login_required
def closing_entry_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """Closing-entry detail page — also handles inline save for DRAFT rows.

    - GET: render the detail page. For DRAFT, the reconciliation table is
      an inline-editable form (one `closing_amount` input per row, posting
      back here). For SUBMITTED/CANCELLED, it's read-only.
    - POST: save the entered closing amounts for DRAFT entries only, then
      redirect back to this page (PRG pattern).
    """
    closing = get_object_or_404(
        POSClosingEntry.objects.select_related("cashier", "opening_entry"),
        pk=pk,
    )
    closing_payments = list(closing.closing_payments.select_related("mode_of_payment"))

    if request.method == "POST":
        if closing.status != POSClosingEntry.DRAFT:
            messages.error(request, "Only draft closing entries can be edited.")
            return redirect("staff:closing_entry_detail", pk=closing.pk)
        form_data, all_valid = _validate_closing_payment_forms(request, closing_payments)
        if all_valid:
            with transaction.atomic():
                for _cp, form in form_data:
                    form.save()
            messages.success(request, f"Closing entry #{closing.pk} updated.")
            return redirect("staff:closing_entry_detail", pk=closing.pk)
        # Re-render with errors using the bound form_data.
        return render(
            request,
            "backoffice/staff/closing_entry_detail.html",
            {"closing": closing, "form_data": form_data, "closing_payments": closing_payments},
        )

    # GET
    if closing.status == POSClosingEntry.DRAFT:
        form_data = [(cp, ClosingPaymentForm(instance=cp, prefix=f"cp_{cp.pk}")) for cp in closing_payments]
    else:
        form_data = None
    return render(
        request,
        "backoffice/staff/closing_entry_detail.html",
        {"closing": closing, "form_data": form_data, "closing_payments": closing_payments},
    )


def _validate_closing_payment_forms(request, closing_payments):
    """Bind one `ClosingPaymentForm` per row and return (form_data, all_valid)."""
    form_data = []
    all_valid = True
    for cp in closing_payments:
        form = ClosingPaymentForm(request.POST, instance=cp, prefix=f"cp_{cp.pk}")
        if not form.is_valid():
            all_valid = False
        form_data.append((cp, form))
    return form_data, all_valid


@login_required
@require_POST
def closing_entry_submit(request: HttpRequest, pk: int) -> HttpResponse:
    closing = get_object_or_404(POSClosingEntry, pk=pk)
    if closing.status != POSClosingEntry.DRAFT:
        messages.error(request, "This closing entry is no longer in draft.")
        return redirect("staff:closing_entry_detail", pk=closing.pk)
    try:
        closing.full_clean()
        closing.submit()
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect("staff:closing_entry_detail", pk=closing.pk)
    except Exception:
        logger.exception("Closing entry submission failed", extra={"closing_entry_id": closing.pk})
        messages.error(request, "Cannot submit the closing entry.")
        return redirect("staff:closing_entry_detail", pk=closing.pk)
    messages.success(
        request,
        f"Shift closed. Closing entry #{closing.pk} submitted; "
        f"opening entry #{closing.opening_entry_id} marked Closed.",
    )
    return redirect("staff:closing_entry_detail", pk=closing.pk)


@login_required
@require_POST
def closing_entry_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    closing = get_object_or_404(POSClosingEntry, pk=pk)
    try:
        closing.cancel(by_user=request.user)
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect("staff:closing_entry_detail", pk=closing.pk)
    except Exception:
        logger.exception("Closing entry cancellation failed", extra={"closing_entry_id": closing.pk})
        messages.error(request, "Cannot cancel the closing entry.")
        return redirect("staff:closing_entry_detail", pk=closing.pk)
    messages.success(request, f"Closing entry #{closing.pk} cancelled.")
    return redirect("staff:closing_entry_list")

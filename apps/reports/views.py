"""Daily P&L backoffice views. Manager/Admin only."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.users.models import CustomUser
from apps.utils.forms import add_formset_row, remove_formset_row

from .forms import (
    DailyPnLAdHocFormSet,
    DailyPnLForm,
    DailyPnLMaterialQtyFormSet,
    PnLConfigurationForm,
    PnLMaterialFormSet,
    PnLRecurringExpenseFormSet,
)
from .models import DailyPnL, PnLConfiguration, PnLMaterial, PnLRecurringExpense
from .services import compute_daily_pnl


def _authenticated_user(request: HttpRequest) -> CustomUser:
    user = request.user
    if not isinstance(user, CustomUser):
        raise PermissionDenied
    return user


def _require_manager(request: HttpRequest) -> CustomUser:
    user = _authenticated_user(request)
    if not (user.is_manager or user.is_admin or user.is_superuser):
        raise PermissionDenied
    return user


def _seed_material_rows(pnl):
    existing = set(pnl.material_qtys.values_list("material_id", flat=True))
    for material in PnLMaterial.objects.filter(disabled=False):
        if material.pk not in existing:
            pnl.material_qtys.create(material=material, qty=0)


@login_required
def pnl_settings(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    config = PnLConfiguration.load()
    form = PnLConfigurationForm(request.POST or None, instance=config)
    materials = PnLMaterialFormSet(request.POST or None, queryset=PnLMaterial.objects.all(), prefix="materials")
    expenses = PnLRecurringExpenseFormSet(
        request.POST or None, queryset=PnLRecurringExpense.objects.all(), prefix="expenses"
    )
    if request.method == "POST" and form.is_valid() and materials.is_valid() and expenses.is_valid():
        with transaction.atomic():
            form.save()
            materials.save()
            expenses.save()
        messages.success(request, "P&L settings saved.")
        return redirect("reports:pnl_settings")
    return render(
        request,
        "backoffice/reports/pnl_settings.html",
        {"form": form, "materials": materials, "expenses": expenses, "show_errors": request.method == "POST"},
    )


@login_required
def daily_pnl_list(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    qs = DailyPnL.objects.all()
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    date_from = request.GET.get("from")
    date_to = request.GET.get("to")
    if date_from:
        qs = qs.filter(business_date__gte=date_from)
    if date_to:
        qs = qs.filter(business_date__lte=date_to)
    return render(
        request,
        "backoffice/reports/daily_pnl_list.html",
        {"entries": qs, "status": status or "", "date_from": date_from or "", "date_to": date_to or ""},
    )


@login_required
def daily_pnl_create(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    form = DailyPnLForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        pnl = form.save()
        _seed_material_rows(pnl)
        messages.success(request, f"Daily P&L draft for {pnl.business_date} created.")
        return redirect("reports:daily_pnl_update", pk=pnl.pk)
    return render(request, "backoffice/reports/daily_pnl_form.html", {"form": form, "is_create": True})


def _form_context(pnl, form, materials, adhoc, *, show_errors, preview=None):
    return {
        "form": form,
        "materials": materials,
        "adhoc": adhoc,
        "pnl": pnl,
        "is_create": False,
        "show_errors": show_errors,
        "preview": preview,
    }


@login_required
def daily_pnl_update(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    pnl = get_object_or_404(DailyPnL, pk=pk)
    if pnl.status != DailyPnL.DRAFT:
        messages.error(request, "Only draft Daily P&L documents can be edited.")
        return redirect("reports:daily_pnl_detail", pk=pnl.pk)
    form = DailyPnLForm(request.POST or None, instance=pnl)
    materials = DailyPnLMaterialQtyFormSet(request.POST or None, instance=pnl, prefix="materials")
    adhoc = DailyPnLAdHocFormSet(request.POST or None, instance=pnl, prefix="adhoc")
    if request.method == "POST" and form.is_valid() and materials.is_valid() and adhoc.is_valid():
        with transaction.atomic():
            form.save()
            materials.save()
            adhoc.save()
        messages.success(request, "Draft saved.")
        return redirect("reports:daily_pnl_update", pk=pnl.pk)
    preview = None
    if request.method != "POST":
        try:
            preview = compute_daily_pnl(pnl)
        except ValidationError:
            preview = None
    return render(
        request,
        "backoffice/reports/daily_pnl_form.html",
        _form_context(pnl, form, materials, adhoc, show_errors=request.method == "POST", preview=preview),
    )


@login_required
def daily_pnl_detail(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    pnl = get_object_or_404(DailyPnL.objects.select_related("amended_from", "submitted_by"), pk=pk)
    return render(
        request,
        "backoffice/reports/daily_pnl_detail.html",
        {
            "pnl": pnl,
            "lines": pnl.lines.all(),
            "cogs_rows": pnl.cogs_rows.all(),
            "consumption_rows": pnl.consumption_rows.all(),
        },
    )


@login_required
@require_POST
def daily_pnl_preview(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    pnl = get_object_or_404(DailyPnL, pk=pk)
    if pnl.status != DailyPnL.DRAFT:
        return HttpResponse("Only drafts can be previewed.", status=400)
    form = DailyPnLForm(request.POST, instance=pnl)
    materials = DailyPnLMaterialQtyFormSet(request.POST, instance=pnl, prefix="materials")
    adhoc = DailyPnLAdHocFormSet(request.POST, instance=pnl, prefix="adhoc")
    if form.is_valid() and materials.is_valid() and adhoc.is_valid():
        with transaction.atomic():
            form.save()
            materials.save()
            adhoc.save()
        pnl.refresh_from_db()
        try:
            preview = compute_daily_pnl(pnl)
        except ValidationError as e:
            return render(
                request,
                "backoffice/reports/_statement.html",
                {"preview_error": e.messages[0] if e.messages else str(e)},
            )
        return render(request, "backoffice/reports/_statement.html", {"preview": preview, "pnl": pnl})
    return render(
        request,
        "backoffice/reports/daily_pnl_form.html",
        _form_context(pnl, form, materials, adhoc, show_errors=True),
    )


@login_required
@require_POST
def daily_pnl_submit(request: HttpRequest, pk: int) -> HttpResponse:
    user = _require_manager(request)
    pnl = get_object_or_404(DailyPnL, pk=pk)
    try:
        pnl.submit(actor=user)
    except ValidationError as e:
        messages.error(request, e.messages[0] if e.messages else str(e))
        return redirect(
            "reports:daily_pnl_detail" if pnl.status != DailyPnL.DRAFT else "reports:daily_pnl_update", pk=pnl.pk
        )
    messages.success(request, f"Daily P&L for {pnl.business_date} submitted.")
    return redirect("reports:daily_pnl_detail", pk=pnl.pk)


@login_required
@require_POST
def daily_pnl_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    pnl = get_object_or_404(DailyPnL, pk=pk)
    try:
        pnl.cancel()
    except ValidationError as e:
        messages.error(request, e.messages[0] if e.messages else str(e))
        return redirect("reports:daily_pnl_detail", pk=pnl.pk)
    messages.success(request, f"Daily P&L for {pnl.business_date} cancelled.")
    return redirect("reports:daily_pnl_list")


@login_required
@require_POST
def daily_pnl_amend(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    pnl = get_object_or_404(DailyPnL, pk=pk)
    try:
        copy = pnl.amend()
    except ValidationError as e:
        messages.error(request, e.messages[0] if e.messages else str(e))
        return redirect("reports:daily_pnl_detail", pk=pnl.pk)
    messages.success(request, f"Amendment created — edit the draft for {copy.business_date}.")
    return redirect("reports:daily_pnl_update", pk=copy.pk)


@login_required
@require_POST
def daily_pnl_material_add(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    pnl = get_object_or_404(DailyPnL, pk=pk)
    formset = add_formset_row(DailyPnLMaterialQtyFormSet, "materials", request.POST)
    return render(
        request,
        "backoffice/reports/_material_formset.html",
        {"materials": formset, "pnl": pnl, "show_errors": False},
    )


@login_required
@require_POST
def daily_pnl_material_remove(request: HttpRequest, pk: int, index: int) -> HttpResponse:
    _require_manager(request)
    pnl = get_object_or_404(DailyPnL, pk=pk)
    formset = remove_formset_row(DailyPnLMaterialQtyFormSet, "materials", request.POST, index)
    return render(
        request,
        "backoffice/reports/_material_formset.html",
        {"materials": formset, "pnl": pnl, "show_errors": False},
    )


@login_required
@require_POST
def daily_pnl_adhoc_add(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    pnl = get_object_or_404(DailyPnL, pk=pk)
    formset = add_formset_row(DailyPnLAdHocFormSet, "adhoc", request.POST)
    return render(
        request,
        "backoffice/reports/_adhoc_formset.html",
        {"adhoc": formset, "pnl": pnl, "show_errors": False},
    )


@login_required
@require_POST
def daily_pnl_adhoc_remove(request: HttpRequest, pk: int, index: int) -> HttpResponse:
    _require_manager(request)
    pnl = get_object_or_404(DailyPnL, pk=pk)
    formset = remove_formset_row(DailyPnLAdHocFormSet, "adhoc", request.POST, index)
    return render(
        request,
        "backoffice/reports/_adhoc_formset.html",
        {"adhoc": formset, "pnl": pnl, "show_errors": False},
    )

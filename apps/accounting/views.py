"""Accounting backoffice views — chart of accounts, journal entries, GL entries,
fiscal years, cost centers. All behind the backoffice role gate."""

from decimal import Decimal

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
    CostCenterForm,
    FiscalYearForm,
    JournalEntryAccountFormSet,
    JournalEntryForm,
    LedgerAccountForm,
)
from .models import CostCenter, FiscalYear, GLEntry, JournalEntry, LedgerAccount


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


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@login_required
def accounting_dashboard(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    from .payables_models import Supplier, SupplierInvoice, SupplierPayment

    return render(
        request,
        "backoffice/accounting/dashboard.html",
        {
            "account_count": LedgerAccount.objects.count(),
            "journal_count": JournalEntry.objects.count(),
            "gl_entry_count": GLEntry.objects.count(),
            "fiscal_year_count": FiscalYear.objects.count(),
            "cost_center_count": CostCenter.objects.count(),
            "supplier_count": Supplier.objects.count(),
            "invoice_count": SupplierInvoice.objects.count(),
            "unpaid_invoice_count": SupplierInvoice.objects.filter(
                status=SupplierInvoice.SUBMITTED, outstanding_amount__gt=0
            ).count(),
            "payment_count": SupplierPayment.objects.count(),
            "outstanding_total": sum((s.outstanding_balance for s in Supplier.objects.all()), Decimal("0")),
        },
    )


# ---------------------------------------------------------------------------
# Chart of Accounts
# ---------------------------------------------------------------------------


@login_required
def chart_of_accounts(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    roots = (
        LedgerAccount.objects.filter(parent__isnull=True)
        .prefetch_related("children__children__children")
        .order_by("name")
    )
    return render(request, "backoffice/accounting/chart_of_accounts.html", {"roots": roots})


@login_required
def account_children(request: HttpRequest, pk: int) -> HttpResponse:
    """HTMX fragment of one account's children for expand/collapse."""
    _require_manager(request)
    account = get_object_or_404(
        LedgerAccount.objects.prefetch_related("children__children"),
        pk=pk,
    )
    depth = int(request.GET.get("depth", "1"))
    return render(
        request,
        "backoffice/accounting/_account_children.html",
        {"account": account, "depth": depth},
    )


@login_required
def account_create(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    if request.method == "POST":
        form = LedgerAccountForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Account created.")
            return redirect("accounting:chart_of_accounts")
    else:
        form = LedgerAccountForm()
    return render(request, "backoffice/accounting/account_form.html", {"form": form, "is_create": True})


@login_required
def account_detail(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    account = get_object_or_404(LedgerAccount.objects.select_related("parent"), pk=pk)
    return render(request, "backoffice/accounting/account_detail.html", {"account": account})


@login_required
def account_update(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    account = get_object_or_404(LedgerAccount, pk=pk)
    if request.method == "POST":
        form = LedgerAccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, "Account updated.")
            return redirect("accounting:account_detail", pk=account.pk)
    else:
        form = LedgerAccountForm(instance=account)
    return render(
        request,
        "backoffice/accounting/account_form.html",
        {"form": form, "is_create": False, "account": account},
    )


# ---------------------------------------------------------------------------
# Journal Entries
# ---------------------------------------------------------------------------


@login_required
def journal_entry_list(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    entries = JournalEntry.objects.select_related("amended_from").order_by("-posting_date", "-pk")
    return render(request, "backoffice/accounting/journal_entry_list.html", {"entries": entries})


@login_required
def journal_entry_create(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    form = JournalEntryForm(request.POST or None)
    formset = JournalEntryAccountFormSet(request.POST or None, prefix="accounts")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            journal = form.save()
            formset.instance = journal
            formset.save()
        return redirect("accounting:journal_entry_detail", pk=journal.pk)
    return render(
        request,
        "backoffice/accounting/journal_entry_form.html",
        {"form": form, "formset": formset, "is_create": True, "show_errors": request.method == "POST"},
    )


@login_required
@require_POST
def journal_entry_account_add(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    formset = add_formset_row(JournalEntryAccountFormSet, "accounts", request.POST)
    return render(
        request,
        "backoffice/accounting/journal_entry_form.html#accounts_partial",
        {"formset": formset},
    )


@login_required
@require_POST
def journal_entry_account_remove(request: HttpRequest, index: int) -> HttpResponse:
    _require_manager(request)
    formset = remove_formset_row(JournalEntryAccountFormSet, "accounts", request.POST, index)
    return render(
        request,
        "backoffice/accounting/journal_entry_form.html#accounts_partial",
        {"formset": formset},
    )


@login_required
def journal_entry_detail(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    journal = get_object_or_404(JournalEntry.objects.select_related("amended_from"), pk=pk)
    rows = journal.accounts.select_related("account", "cost_center").all()
    return render(
        request,
        "backoffice/accounting/journal_entry_detail.html",
        {"journal": journal, "rows": rows},
    )


@login_required
def journal_entry_update(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    journal = get_object_or_404(JournalEntry, pk=pk)
    if journal.status != JournalEntry.DRAFT:
        messages.error(request, "Only draft journal entries can be edited.")
        return redirect("accounting:journal_entry_detail", pk=journal.pk)
    form = JournalEntryForm(request.POST or None, instance=journal)
    formset = JournalEntryAccountFormSet(request.POST or None, instance=journal, prefix="accounts")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            form.save()
            formset.save()
        return redirect("accounting:journal_entry_detail", pk=journal.pk)
    return render(
        request,
        "backoffice/accounting/journal_entry_form.html",
        {
            "form": form,
            "formset": formset,
            "is_create": False,
            "journal": journal,
            "show_errors": request.method == "POST",
        },
    )


@login_required
def journal_entry_review(request: HttpRequest, pk: int) -> HttpResponse:
    """Read-only review screen that must precede submitting an opening entry."""
    _require_manager(request)
    journal = get_object_or_404(JournalEntry.objects.select_related("amended_from"), pk=pk)
    if journal.voucher_type != JournalEntry.OPENING or journal.status != JournalEntry.DRAFT:
        return redirect("accounting:journal_entry_detail", pk=journal.pk)
    journal._recompute_totals()
    rows = journal.accounts.select_related("account", "cost_center").all()
    return render(
        request,
        "backoffice/accounting/journal_entry_review.html",
        {"journal": journal, "rows": rows},
    )


@login_required
@require_POST
def journal_entry_submit(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    journal = get_object_or_404(JournalEntry, pk=pk)
    if journal.voucher_type == JournalEntry.OPENING and request.POST.get("confirmed") != "1":
        return redirect("accounting:journal_entry_review", pk=journal.pk)
    try:
        journal.submit()
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect("accounting:journal_entry_detail", pk=journal.pk)
    messages.success(request, f"Journal entry #{journal.pk} submitted.")
    return redirect("accounting:journal_entry_detail", pk=journal.pk)


@login_required
@require_POST
def journal_entry_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    journal = get_object_or_404(JournalEntry, pk=pk)
    try:
        journal.cancel()
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect("accounting:journal_entry_detail", pk=journal.pk)
    messages.success(request, f"Journal entry #{journal.pk} cancelled.")
    return redirect("accounting:journal_entry_list")


@login_required
@require_POST
def journal_entry_amend(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    journal = get_object_or_404(JournalEntry, pk=pk)
    try:
        copy = journal.amend()
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect("accounting:journal_entry_detail", pk=journal.pk)
    messages.success(request, f"Amendment created — edit and submit journal entry #{copy.pk}.")
    return redirect("accounting:journal_entry_update", pk=copy.pk)


# ---------------------------------------------------------------------------
# GL Entries (read-only)
# ---------------------------------------------------------------------------


@login_required
def gl_entry_list(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    qs = GLEntry.objects.select_related("account", "cost_center", "fiscal_year").order_by("-posting_date", "-pk")
    account_id = request.GET.get("account")
    voucher_type = request.GET.get("voucher_type")
    include_cancelled = request.GET.get("include_cancelled") == "1"
    if account_id:
        qs = qs.filter(account_id=int(account_id))
    if voucher_type:
        qs = qs.filter(voucher_type=voucher_type)
    if not include_cancelled:
        qs = qs.filter(is_cancelled=False)
    return render(
        request,
        "backoffice/accounting/gl_entry_list.html",
        {
            "entries": qs,
            "accounts": LedgerAccount.objects.filter(is_group=False).order_by("name"),
            "voucher_types": GLEntry.objects.values_list("voucher_type", flat=True).distinct().order_by(),
            "account_id": account_id,
            "voucher_type": voucher_type,
            "include_cancelled": include_cancelled,
        },
    )


# ---------------------------------------------------------------------------
# Fiscal Years
# ---------------------------------------------------------------------------


@login_required
def fiscal_year_list(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    years = FiscalYear.objects.all().order_by("-year_start_date")
    return render(request, "backoffice/accounting/fiscal_year_list.html", {"years": years})


@login_required
def fiscal_year_create(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    if request.method == "POST":
        form = FiscalYearForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("accounting:fiscal_year_list")
    else:
        form = FiscalYearForm()
    return render(
        request,
        "backoffice/accounting/fiscal_year_form.html",
        {"form": form, "is_create": True},
    )


@login_required
def fiscal_year_update(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    year = get_object_or_404(FiscalYear, pk=pk)
    if request.method == "POST":
        form = FiscalYearForm(request.POST, instance=year)
        if form.is_valid():
            form.save()
            return redirect("accounting:fiscal_year_list")
    else:
        form = FiscalYearForm(instance=year)
    return render(
        request,
        "backoffice/accounting/fiscal_year_form.html",
        {"form": form, "is_create": False, "year": year},
    )


# ---------------------------------------------------------------------------
# Cost Centers
# ---------------------------------------------------------------------------


@login_required
def cost_center_list(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    centers = CostCenter.objects.all().order_by("name")
    return render(request, "backoffice/accounting/cost_center_list.html", {"centers": centers})


@login_required
def cost_center_create(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    if request.method == "POST":
        form = CostCenterForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("accounting:cost_center_list")
    else:
        form = CostCenterForm()
    return render(
        request,
        "backoffice/accounting/cost_center_form.html",
        {"form": form, "is_create": True},
    )


@login_required
def cost_center_update(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    center = get_object_or_404(CostCenter, pk=pk)
    if request.method == "POST":
        form = CostCenterForm(request.POST, instance=center)
        if form.is_valid():
            form.save()
            return redirect("accounting:cost_center_list")
    else:
        form = CostCenterForm(instance=center)
    return render(
        request,
        "backoffice/accounting/cost_center_form.html",
        {"form": form, "is_create": False, "center": center},
    )

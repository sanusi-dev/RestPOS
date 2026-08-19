"""Supplier payables views — suppliers, supplier invoices, and supplier payments.

All behind the backoffice role gate (Manager/Admin), mirroring the accounting
app's other registers.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.users.models import CustomUser
from apps.utils.forms import add_formset_row, remove_formset_row

from .models import GLEntry
from .payables_forms import (
    SupplierForm,
    SupplierInvoiceForm,
    SupplierInvoiceItemFormSet,
    SupplierPaymentAllocationFormSet,
    SupplierPaymentForm,
)
from .payables_models import (
    Supplier,
    SupplierInvoice,
    SupplierPayment,
)


def _require_manager(request: HttpRequest) -> CustomUser:
    user = request.user
    if not isinstance(user, CustomUser):
        raise PermissionDenied
    if not (user.is_manager or user.is_admin or user.is_superuser):
        raise PermissionDenied
    return user


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------


@login_required
def supplier_list(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    suppliers = Supplier.objects.prefetch_related("invoices").order_by("supplier_name")
    return render(request, "backoffice/accounting/payables/supplier_list.html", {"suppliers": suppliers})


@login_required
def supplier_create(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier created.")
            return redirect("accounting:supplier_list")
    else:
        form = SupplierForm()
    return render(request, "backoffice/accounting/payables/supplier_form.html", {"form": form, "is_create": True})


@login_required
def supplier_detail(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    supplier = get_object_or_404(Supplier, pk=pk)
    invoices = supplier.invoices.all().order_by("-posting_date", "-pk")
    payments = supplier.payments.all().order_by("-posting_date", "-pk")
    return render(
        request,
        "backoffice/accounting/payables/supplier_detail.html",
        {"supplier": supplier, "invoices": invoices, "payments": payments},
    )


@login_required
def supplier_update(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == "POST":
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier updated.")
            return redirect("accounting:supplier_detail", pk=supplier.pk)
    else:
        form = SupplierForm(instance=supplier)
    return render(
        request,
        "backoffice/accounting/payables/supplier_form.html",
        {"form": form, "is_create": False, "supplier": supplier},
    )


# ---------------------------------------------------------------------------
# Supplier Invoices
# ---------------------------------------------------------------------------


@login_required
def supplier_invoice_list(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    invoices = SupplierInvoice.objects.select_related("supplier").order_by("-posting_date", "-pk")
    status = request.GET.get("status")
    supplier_id = request.GET.get("supplier")
    if status:
        invoices = invoices.filter(status=status)
    if supplier_id:
        invoices = invoices.filter(supplier_id=supplier_id)
    return render(
        request,
        "backoffice/accounting/payables/supplier_invoice_list.html",
        {
            "invoices": invoices,
            "suppliers": Supplier.objects.filter(disabled=False),
            "selected_status": status,
            "selected_supplier": supplier_id,
        },
    )


@login_required
def supplier_invoice_create(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    if request.method == "POST":
        form = SupplierInvoiceForm(request.POST)
        item_fs = SupplierInvoiceItemFormSet(request.POST, instance=SupplierInvoice(), prefix="items")
        if form.is_valid() and item_fs.is_valid():
            with transaction.atomic():
                invoice = form.save()
                item_fs.instance = invoice
                item_fs.save()
            messages.success(request, "Supplier invoice draft created.")
            return redirect("accounting:supplier_invoice_detail", pk=invoice.pk)
    else:
        form = SupplierInvoiceForm()
        item_fs = SupplierInvoiceItemFormSet(instance=SupplierInvoice(), prefix="items")
    return render(
        request,
        "backoffice/accounting/payables/supplier_invoice_form.html",
        {"form": form, "is_create": True, "item_formset": item_fs, "show_errors": request.method == "POST"},
    )


@login_required
@require_POST
def supplier_invoice_item_add(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    formset = add_formset_row(SupplierInvoiceItemFormSet, "items", request.POST)
    return render(
        request,
        "backoffice/accounting/payables/supplier_invoice_form.html#items_partial",
        {"item_formset": formset},
    )


@login_required
@require_POST
def supplier_invoice_item_remove(request: HttpRequest, index: int) -> HttpResponse:
    _require_manager(request)
    formset = remove_formset_row(SupplierInvoiceItemFormSet, "items", request.POST, index)
    return render(
        request,
        "backoffice/accounting/payables/supplier_invoice_form.html#items_partial",
        {"item_formset": formset},
    )


@login_required
def supplier_invoice_detail(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    invoice = get_object_or_404(
        SupplierInvoice.objects.select_related("supplier", "purchase_receipt"),
        pk=pk,
    )
    items = invoice.items.select_related("item", "source_receipt_line", "expense_account", "cost_center").all()
    gl_entries = GLEntry.objects.filter(
        voucher_type="Supplier Invoice", voucher_no=invoice.invoice_number
    ).select_related("account", "fiscal_year")
    return render(
        request,
        "backoffice/accounting/payables/supplier_invoice_detail.html",
        {"invoice": invoice, "items": items, "gl_entries": gl_entries},
    )


@login_required
def supplier_invoice_update(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    invoice = get_object_or_404(SupplierInvoice, pk=pk)
    if invoice.status != SupplierInvoice.DRAFT:
        messages.error(request, "Only draft supplier invoices can be edited.")
        return redirect("accounting:supplier_invoice_detail", pk=pk)
    if request.method == "POST":
        form = SupplierInvoiceForm(request.POST, instance=invoice)
        item_fs = SupplierInvoiceItemFormSet(request.POST, instance=invoice, prefix="items")
        if form.is_valid() and item_fs.is_valid():
            with transaction.atomic():
                form.save()
                item_fs.save()
            messages.success(request, "Supplier invoice updated.")
            return redirect("accounting:supplier_invoice_detail", pk=invoice.pk)
    else:
        form = SupplierInvoiceForm(instance=invoice)
        item_fs = SupplierInvoiceItemFormSet(instance=invoice, prefix="items")
    return render(
        request,
        "backoffice/accounting/payables/supplier_invoice_form.html",
        {"form": form, "is_create": False, "item_formset": item_fs, "show_errors": request.method == "POST"},
    )


@login_required
@require_POST
def supplier_invoice_submit(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    invoice = get_object_or_404(SupplierInvoice, pk=pk)
    try:
        invoice.submit()
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("accounting:supplier_invoice_detail", pk=pk)
    messages.success(request, f"Supplier invoice {invoice.invoice_number} submitted.")
    return redirect("accounting:supplier_invoice_detail", pk=pk)


@login_required
@require_POST
def supplier_invoice_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    invoice = get_object_or_404(SupplierInvoice, pk=pk)
    try:
        invoice.cancel()
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("accounting:supplier_invoice_detail", pk=pk)
    messages.success(request, f"Supplier invoice {invoice.invoice_number} cancelled.")
    return redirect("accounting:supplier_invoice_list")


# ---------------------------------------------------------------------------
# Supplier Payments
# ---------------------------------------------------------------------------


@login_required
def supplier_payment_list(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    payments = SupplierPayment.objects.select_related("supplier", "mode_of_payment").order_by("-posting_date", "-pk")
    status = request.GET.get("status")
    supplier_id = request.GET.get("supplier")
    if status:
        payments = payments.filter(status=status)
    if supplier_id:
        payments = payments.filter(supplier_id=supplier_id)
    return render(
        request,
        "backoffice/accounting/payables/supplier_payment_list.html",
        {
            "payments": payments,
            "suppliers": Supplier.objects.filter(disabled=False),
            "selected_status": status,
            "selected_supplier": supplier_id,
        },
    )


@login_required
def supplier_payment_create(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    if request.method == "POST":
        form = SupplierPaymentForm(request.POST)
        alloc_fs = SupplierPaymentAllocationFormSet(request.POST, instance=SupplierPayment(), prefix="allocations")
        if form.is_valid() and alloc_fs.is_valid():
            with transaction.atomic():
                payment = form.save()
                alloc_fs.instance = payment
                alloc_fs.save()
            messages.success(request, "Supplier payment draft created.")
            return redirect("accounting:supplier_payment_detail", pk=payment.pk)
    else:
        form = SupplierPaymentForm()
        alloc_fs = SupplierPaymentAllocationFormSet(instance=SupplierPayment(), prefix="allocations")
    return render(
        request,
        "backoffice/accounting/payables/supplier_payment_form.html",
        {"form": form, "is_create": True, "alloc_formset": alloc_fs, "show_errors": request.method == "POST"},
    )


@login_required
@require_POST
def supplier_payment_alloc_add(request: HttpRequest) -> HttpResponse:
    _require_manager(request)
    formset = add_formset_row(SupplierPaymentAllocationFormSet, "allocations", request.POST)
    return render(
        request,
        "backoffice/accounting/payables/supplier_payment_form.html#allocations_partial",
        {"alloc_formset": formset},
    )


@login_required
@require_POST
def supplier_payment_alloc_remove(request: HttpRequest, index: int) -> HttpResponse:
    _require_manager(request)
    formset = remove_formset_row(SupplierPaymentAllocationFormSet, "allocations", request.POST, index)
    return render(
        request,
        "backoffice/accounting/payables/supplier_payment_form.html#allocations_partial",
        {"alloc_formset": formset},
    )


@login_required
def supplier_payment_detail(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    payment = get_object_or_404(
        SupplierPayment.objects.select_related("supplier", "mode_of_payment"),
        pk=pk,
    )
    allocations = payment.allocations.select_related("invoice", "invoice__supplier").all()
    gl_entries = GLEntry.objects.filter(
        voucher_type="Supplier Payment", voucher_no=payment.payment_number
    ).select_related("account", "fiscal_year")
    return render(
        request,
        "backoffice/accounting/payables/supplier_payment_detail.html",
        {"payment": payment, "allocations": allocations, "gl_entries": gl_entries},
    )


@login_required
def supplier_payment_update(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    payment = get_object_or_404(SupplierPayment, pk=pk)
    if payment.status != SupplierPayment.DRAFT:
        messages.error(request, "Only draft supplier payments can be edited.")
        return redirect("accounting:supplier_payment_detail", pk=pk)
    if request.method == "POST":
        form = SupplierPaymentForm(request.POST, instance=payment)
        alloc_fs = SupplierPaymentAllocationFormSet(request.POST, instance=payment, prefix="allocations")
        if form.is_valid() and alloc_fs.is_valid():
            with transaction.atomic():
                form.save()
                alloc_fs.save()
            messages.success(request, "Supplier payment updated.")
            return redirect("accounting:supplier_payment_detail", pk=payment.pk)
    else:
        form = SupplierPaymentForm(instance=payment)
        alloc_fs = SupplierPaymentAllocationFormSet(instance=payment, prefix="allocations")
    return render(
        request,
        "backoffice/accounting/payables/supplier_payment_form.html",
        {"form": form, "is_create": False, "alloc_formset": alloc_fs, "show_errors": request.method == "POST"},
    )


@login_required
@require_POST
def supplier_payment_submit(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    payment = get_object_or_404(SupplierPayment, pk=pk)
    try:
        payment.submit()
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("accounting:supplier_payment_detail", pk=pk)
    messages.success(request, f"Supplier payment {payment.payment_number} submitted.")
    return redirect("accounting:supplier_payment_detail", pk=pk)


@login_required
@require_POST
def supplier_payment_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    _require_manager(request)
    payment = get_object_or_404(SupplierPayment, pk=pk)
    try:
        payment.cancel()
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("accounting:supplier_payment_detail", pk=pk)
    messages.success(request, f"Supplier payment {payment.payment_number} cancelled.")
    return redirect("accounting:supplier_payment_list")

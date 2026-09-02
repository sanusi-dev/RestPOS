"""Supplier payables views — suppliers, invoices, and payments."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.users.decorators import manager_required
from apps.utils.forms import add_formset_row, remove_formset_row

from .models import GLEntry
from .payables_forms import (
    SupplierForm,
    SupplierInvoiceExpenseFormSet,
    SupplierInvoiceForm,
    SupplierPaymentAllocationFormSet,
    SupplierPaymentForm,
)
from .payables_models import (
    Supplier,
    SupplierInvoice,
    SupplierPayment,
)


@manager_required
def supplier_list(request: HttpRequest) -> HttpResponse:
    suppliers = Supplier.objects.prefetch_related("invoices").order_by("supplier_name")
    return render(request, "backoffice/accounting/payables/supplier_list.html", {"suppliers": suppliers})


@manager_required
def supplier_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier created.")
            return redirect("accounting:supplier_list")
    else:
        form = SupplierForm()
    return render(request, "backoffice/accounting/payables/supplier_form.html", {"form": form, "is_create": True})


@manager_required
def supplier_detail(request: HttpRequest, pk: int) -> HttpResponse:
    supplier = get_object_or_404(Supplier, pk=pk)
    invoices = supplier.invoices.all().order_by("-posting_date", "-pk")
    payments = supplier.payments.all().order_by("-posting_date", "-pk")
    return render(
        request,
        "backoffice/accounting/payables/supplier_detail.html",
        {"supplier": supplier, "invoices": invoices, "payments": payments},
    )


@manager_required
def supplier_update(request: HttpRequest, pk: int) -> HttpResponse:
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


@manager_required
def supplier_invoice_list(request: HttpRequest) -> HttpResponse:
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


@manager_required
def supplier_invoice_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = SupplierInvoiceForm(request.POST)
        expense_fs = SupplierInvoiceExpenseFormSet(request.POST, instance=SupplierInvoice(), prefix="expenses")
        if form.is_valid() and expense_fs.is_valid():
            with transaction.atomic():
                invoice = form.save()
                expense_fs.instance = invoice
                expense_fs.save()
            messages.success(request, "Supplier invoice draft created.")
            return redirect("accounting:supplier_invoice_detail", pk=invoice.pk)
    else:
        form = SupplierInvoiceForm()
        expense_fs = SupplierInvoiceExpenseFormSet(instance=SupplierInvoice(), prefix="expenses")
    return render(
        request,
        "backoffice/accounting/payables/supplier_invoice_form.html",
        {"form": form, "is_create": True, "expense_formset": expense_fs},
    )


@manager_required
@require_POST
def supplier_invoice_expense_add(request: HttpRequest) -> HttpResponse:
    formset = add_formset_row(SupplierInvoiceExpenseFormSet, "expenses", request.POST)
    return render(
        request,
        "backoffice/accounting/payables/supplier_invoice_form.html#expenses_partial",
        {"expense_formset": formset},
    )


@manager_required
@require_POST
def supplier_invoice_expense_remove(request: HttpRequest, index: int) -> HttpResponse:
    formset = remove_formset_row(SupplierInvoiceExpenseFormSet, "expenses", request.POST, index)
    return render(
        request,
        "backoffice/accounting/payables/supplier_invoice_form.html#expenses_partial",
        {"expense_formset": formset},
    )


@manager_required
def supplier_invoice_detail(request: HttpRequest, pk: int) -> HttpResponse:
    invoice = get_object_or_404(
        SupplierInvoice.objects.select_related("supplier", "purchase_receipt"),
        pk=pk,
    )
    items = invoice.items.select_related("item", "source_receipt_line").all()
    expenses = invoice.expenses.all()
    gl_entries = GLEntry.objects.filter(
        voucher_type="Supplier Invoice", voucher_no=invoice.invoice_number
    ).select_related("account", "fiscal_year")
    return render(
        request,
        "backoffice/accounting/payables/supplier_invoice_detail.html",
        {"invoice": invoice, "items": items, "expenses": expenses, "gl_entries": gl_entries},
    )


@manager_required
def supplier_invoice_update(request: HttpRequest, pk: int) -> HttpResponse:
    invoice = get_object_or_404(SupplierInvoice, pk=pk)
    if invoice.status != SupplierInvoice.DRAFT:
        messages.error(request, "Only draft supplier invoices can be edited.")
        return redirect("accounting:supplier_invoice_detail", pk=pk)
    if request.method == "POST":
        form = SupplierInvoiceForm(request.POST, instance=invoice)
        expense_fs = SupplierInvoiceExpenseFormSet(request.POST, instance=invoice, prefix="expenses")
        if form.is_valid() and expense_fs.is_valid():
            with transaction.atomic():
                form.save()
                expense_fs.save()
            messages.success(request, "Supplier invoice updated.")
            return redirect("accounting:supplier_invoice_detail", pk=invoice.pk)
    else:
        form = SupplierInvoiceForm(instance=invoice)
        expense_fs = SupplierInvoiceExpenseFormSet(instance=invoice, prefix="expenses")
    return render(
        request,
        "backoffice/accounting/payables/supplier_invoice_form.html",
        {"form": form, "is_create": False, "expense_formset": expense_fs},
    )


@manager_required
@require_POST
def supplier_invoice_submit(request: HttpRequest, pk: int) -> HttpResponse:
    invoice = get_object_or_404(SupplierInvoice, pk=pk)
    try:
        invoice.submit()
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("accounting:supplier_invoice_detail", pk=pk)
    messages.success(request, f"Supplier invoice {invoice.invoice_number} submitted.")
    return redirect("accounting:supplier_invoice_detail", pk=pk)


@manager_required
@require_POST
def supplier_invoice_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    invoice = get_object_or_404(SupplierInvoice, pk=pk)
    try:
        invoice.cancel()
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("accounting:supplier_invoice_detail", pk=pk)
    messages.success(request, f"Supplier invoice {invoice.invoice_number} cancelled.")
    return redirect("accounting:supplier_invoice_list")


@manager_required
def supplier_payment_list(request: HttpRequest) -> HttpResponse:
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


@manager_required
def supplier_payment_create(request: HttpRequest) -> HttpResponse:
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
        {"form": form, "is_create": True, "alloc_formset": alloc_fs},
    )


@manager_required
@require_POST
def supplier_payment_alloc_add(request: HttpRequest) -> HttpResponse:
    formset = add_formset_row(SupplierPaymentAllocationFormSet, "allocations", request.POST)
    return render(
        request,
        "backoffice/accounting/payables/supplier_payment_form.html#allocations_partial",
        {"alloc_formset": formset},
    )


@manager_required
@require_POST
def supplier_payment_alloc_remove(request: HttpRequest, index: int) -> HttpResponse:
    formset = remove_formset_row(SupplierPaymentAllocationFormSet, "allocations", request.POST, index)
    return render(
        request,
        "backoffice/accounting/payables/supplier_payment_form.html#allocations_partial",
        {"alloc_formset": formset},
    )


@manager_required
def supplier_payment_detail(request: HttpRequest, pk: int) -> HttpResponse:
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


@manager_required
def supplier_payment_update(request: HttpRequest, pk: int) -> HttpResponse:
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
        {"form": form, "is_create": False, "alloc_formset": alloc_fs},
    )


@manager_required
@require_POST
def supplier_payment_submit(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(SupplierPayment, pk=pk)
    try:
        payment.submit()
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("accounting:supplier_payment_detail", pk=pk)
    messages.success(request, f"Supplier payment {payment.payment_number} submitted.")
    return redirect("accounting:supplier_payment_detail", pk=pk)


@manager_required
@require_POST
def supplier_payment_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    payment = get_object_or_404(SupplierPayment, pk=pk)
    try:
        payment.cancel()
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages))
        return redirect("accounting:supplier_payment_detail", pk=pk)
    messages.success(request, f"Supplier payment {payment.payment_number} cancelled.")
    return redirect("accounting:supplier_payment_list")

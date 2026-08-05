import urllib.parse

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    ItemForm,
    ItemGroupForm,
    PurchaseReceiptForm,
    PurchaseReceiptItemFormSet,
    StockEntryDetailFormSet,
    StockEntryForm,
    StockReconciliationForm,
    StockReconciliationItemFormSet,
    UOMForm,
    WarehouseForm,
)
from .models import (
    UOM,
    Bin,
    Item,
    ItemGroup,
    PurchaseReceipt,
    StockEntry,
    StockLedgerEntry,
    StockReconciliation,
    Warehouse,
)


@login_required
def inventory_dashboard(request: HttpRequest) -> HttpResponse:
    low_stock_bins = (
        Bin.objects.select_related("item", "warehouse")
        .filter(actual_qty__lte=models.F("item__safety_stock"), item__safety_stock__gt=0)
        .order_by("item__item_name")
    )
    context = {
        "item_count": Item.objects.count(),
        "item_group_count": ItemGroup.objects.count(),
        "warehouse_count": Warehouse.objects.count(),
        "uom_count": UOM.objects.count(),
        "stock_entry_count": StockEntry.objects.count(),
        "low_stock_bins": low_stock_bins,
    }
    return render(request, "backoffice/inventory/dashboard.html", context)


# ---------------------------------------------------------------------------
# UOM
# ---------------------------------------------------------------------------


@login_required
def uom_list(request: HttpRequest) -> HttpResponse:
    uoms = UOM.objects.all().order_by("name")
    return render(request, "backoffice/inventory/uom_list.html", {"uoms": uoms})


@login_required
def uom_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = UOMForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("inventory:uom_list")
    else:
        form = UOMForm()
    return render(
        request,
        "backoffice/inventory/uom_form.html",
        {"form": form, "is_create": True},
    )


@login_required
def uom_update(request: HttpRequest, pk: int) -> HttpResponse:
    uom = get_object_or_404(UOM, pk=pk)
    if request.method == "POST":
        form = UOMForm(request.POST, instance=uom)
        if form.is_valid():
            form.save()
            return redirect("inventory:uom_list")
    else:
        form = UOMForm(instance=uom)
    return render(
        request,
        "backoffice/inventory/uom_form.html",
        {"form": form, "is_create": False, "uom": uom},
    )


# ---------------------------------------------------------------------------
# ItemGroup
# ---------------------------------------------------------------------------


@login_required
def item_group_list(request: HttpRequest) -> HttpResponse:
    groups = ItemGroup.objects.all().order_by("name")
    return render(request, "backoffice/inventory/item_group_list.html", {"groups": groups})


@login_required
def item_group_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ItemGroupForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("inventory:item_group_list")
    else:
        form = ItemGroupForm()
    return render(
        request,
        "backoffice/inventory/item_group_form.html",
        {"form": form, "is_create": True},
    )


@login_required
def item_group_detail(request: HttpRequest, pk: int) -> HttpResponse:
    group = get_object_or_404(ItemGroup, pk=pk)
    items = group.items.all().order_by("item_name")
    return render(
        request,
        "backoffice/inventory/item_group_detail.html",
        {"group": group, "items": items},
    )


@login_required
def item_group_update(request: HttpRequest, pk: int) -> HttpResponse:
    group = get_object_or_404(ItemGroup, pk=pk)
    if request.method == "POST":
        form = ItemGroupForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
            return redirect("inventory:item_group_detail", pk=group.pk)
    else:
        form = ItemGroupForm(instance=group)
    return render(
        request,
        "backoffice/inventory/item_group_form.html",
        {"form": form, "is_create": False, "group": group},
    )


# ---------------------------------------------------------------------------
# Warehouse
# ---------------------------------------------------------------------------


@login_required
def warehouse_list(request: HttpRequest) -> HttpResponse:
    warehouses = Warehouse.objects.all()
    return render(request, "backoffice/inventory/warehouse_list.html", {"warehouses": warehouses})


@login_required
def warehouse_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = WarehouseForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("inventory:warehouse_list")
    else:
        form = WarehouseForm()
    return render(
        request,
        "backoffice/inventory/warehouse_form.html",
        {"form": form, "is_create": True},
    )


@login_required
def warehouse_detail(request: HttpRequest, pk: int) -> HttpResponse:
    warehouse = get_object_or_404(Warehouse, pk=pk)
    bins = warehouse.bins.select_related("item").order_by("item__item_name")
    return render(
        request,
        "backoffice/inventory/warehouse_detail.html",
        {"warehouse": warehouse, "bins": bins},
    )


@login_required
def warehouse_update(request: HttpRequest, pk: int) -> HttpResponse:
    warehouse = get_object_or_404(Warehouse, pk=pk)
    if request.method == "POST":
        form = WarehouseForm(request.POST, instance=warehouse)
        if form.is_valid():
            form.save()
            return redirect("inventory:warehouse_detail", pk=warehouse.pk)
    else:
        form = WarehouseForm(instance=warehouse)
    return render(
        request,
        "backoffice/inventory/warehouse_form.html",
        {"form": form, "is_create": False, "warehouse": warehouse},
    )


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------


@login_required
def item_list(request: HttpRequest) -> HttpResponse:
    from django.db.models import Q

    item_group_id = request.GET.get("item_group")
    department = request.GET.get("department")
    sellable = request.GET.get("sellable")
    purchasable = request.GET.get("purchasable")
    kind = request.GET.get("kind")
    status = request.GET.get("status", "active")
    q = (request.GET.get("q") or "").strip()

    items = Item.objects.select_related("item_group", "stock_uom", "variant_of")
    if item_group_id:
        items = items.filter(item_group_id=item_group_id)
    if department:
        items = items.filter(department=department)
    if sellable == "1":
        items = items.filter(is_sales_item=True)
    elif sellable == "0":
        items = items.filter(is_sales_item=False)
    if purchasable == "1":
        items = items.filter(is_purchase_item=True)
    elif purchasable == "0":
        items = items.filter(is_purchase_item=False)
    if kind == "template":
        items = items.filter(has_variants=True)
    elif kind == "variant":
        items = items.filter(variant_of__isnull=False)
    elif kind == "plain":
        items = items.filter(has_variants=False, variant_of__isnull=True)
    if status == "active":
        items = items.filter(disabled=False)
    elif status == "disabled":
        items = items.filter(disabled=True)
    if q:
        items = items.filter(Q(item_name__icontains=q) | Q(item_code__icontains=q))

    item_groups = ItemGroup.objects.all().order_by("name")
    return render(
        request,
        "backoffice/inventory/item_list.html",
        {
            "items": items,
            "item_groups": item_groups,
            "selected_item_group": item_group_id,
            "selected_department": department,
            "selected_sellable": sellable,
            "selected_purchasable": purchasable,
            "selected_kind": kind,
            "selected_status": status,
            "search_q": q,
        },
    )


@login_required
def item_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES)
        if form.is_valid():
            item = form.save()
            return redirect("inventory:item_detail", pk=item.pk)
    else:
        form = ItemForm()
    return render(
        request,
        "backoffice/inventory/item_form.html",
        {
            "form": form,
            "is_create": True,
        },
    )


@login_required
def item_detail(request: HttpRequest, pk: int) -> HttpResponse:
    from django.db.models import Exists, OuterRef

    from apps.menu.models import MenuItem

    item = get_object_or_404(
        Item.objects.select_related("item_group", "stock_uom", "default_warehouse", "variant_of"),
        pk=pk,
    )
    bins = item.bins.select_related("warehouse").all()
    on_menu = Exists(MenuItem.objects.filter(item_id=OuterRef("pk"), disabled=False))
    variants = (
        item.variants.annotate(on_menu=on_menu).select_related("item_group", "stock_uom").order_by("item_name")
        if item.has_variants
        else Item.objects.none()
    )
    menu_lines = item.menu_items.select_related("menu").order_by("menu__name")
    return render(
        request,
        "backoffice/inventory/item_detail.html",
        {
            "item": item,
            "bins": bins,
            "variants": variants,
            "menu_lines": menu_lines,
        },
    )


@login_required
def item_update(request: HttpRequest, pk: int) -> HttpResponse:
    # select_related matches item_detail — template/form may access item_group/stock_uom FKs.
    item = get_object_or_404(
        Item.objects.select_related("item_group", "stock_uom", "default_warehouse", "variant_of"),
        pk=pk,
    )
    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES, instance=item)
        if form.is_valid():
            form.save()
            return redirect("inventory:item_detail", pk=item.pk)
    else:
        form = ItemForm(instance=item)
    return render(
        request,
        "backoffice/inventory/item_form.html",
        {
            "form": form,
            "is_create": False,
            "item": item,
        },
    )


# ---------------------------------------------------------------------------
# StockEntry
# ---------------------------------------------------------------------------


@login_required
def stock_entry_list(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status")
    purpose = request.GET.get("purpose")
    entries = StockEntry.objects.all()
    if status:
        entries = entries.filter(status=status)
    if purpose:
        entries = entries.filter(purpose=purpose)
    return render(
        request,
        "backoffice/inventory/stock_entry_list.html",
        {
            "entries": entries,
            "selected_status": status,
            "selected_purpose": purpose,
        },
    )


@login_required
def stock_entry_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = StockEntryForm(request.POST)
        detail_fs = StockEntryDetailFormSet(
            request.POST, instance=StockEntry(purpose=request.POST.get("purpose", "")), prefix="items"
        )
        if form.is_valid() and detail_fs.is_valid():
            with transaction.atomic():
                entry = form.save()
                detail_fs.instance = entry
                detail_fs.save()
            return redirect("inventory:stock_entry_detail", pk=entry.pk)
    else:
        form = StockEntryForm()
        detail_fs = StockEntryDetailFormSet(instance=StockEntry(purpose="MATERIAL_RECEIPT"), prefix="items")
    return render(
        request,
        "backoffice/inventory/stock_entry_form.html",
        {"form": form, "is_create": True, "detail_formset": detail_fs, "show_errors": True},
    )


@login_required
@require_POST
def stock_entry_item_add(request: HttpRequest) -> HttpResponse:
    post_data = request.POST.copy()
    total_forms = int(post_data.get("items-TOTAL_FORMS", 0))

    empty_form = StockEntryDetailFormSet(prefix="items").empty_form
    line_fields = list(empty_form.fields.keys())
    pk_field = empty_form._meta.model._meta.pk.name
    if pk_field not in line_fields:
        line_fields.append(pk_field)

    for field in line_fields:
        post_data[f"items-{total_forms}-{field}"] = ""

    post_data["items-TOTAL_FORMS"] = total_forms + 1

    formset = StockEntryDetailFormSet(post_data, prefix="items")
    return render(
        request, "backoffice/inventory/stock_entry_form.html#detail_items_partial", {"detail_formset": formset}
    )


@login_required
@require_POST
def stock_entry_item_remove(request: HttpRequest, index: int) -> HttpResponse:
    post_data = request.POST.copy()
    total_forms = int(post_data.get("items-TOTAL_FORMS", 0))

    empty_form = StockEntryDetailFormSet(prefix="items").empty_form
    line_fields = list(empty_form.fields.keys())
    pk_field = empty_form._meta.model._meta.pk.name
    if pk_field not in line_fields:
        line_fields.append(pk_field)

    new_data = {}
    new_index = 0

    for i in range(total_forms):
        if i == index:
            continue
        for field in line_fields:
            new_data[f"items-{new_index}-{field}"] = post_data.get(f"items-{i}-{field}", "")
        new_index += 1

    new_data["items-TOTAL_FORMS"] = new_index
    new_data["items-INITIAL_FORMS"] = post_data.get("items-INITIAL_FORMS", 0)
    new_data["items-MIN_NUM_FORMS"] = post_data.get("items-MIN_NUM_FORMS", 0)
    new_data["items-MAX_NUM_FORMS"] = post_data.get("items-MAX_NUM_FORMS", 1000)

    encoded = urllib.parse.urlencode(new_data, doseq=True)
    rebuilt = QueryDict(encoded, mutable=True)

    formset = StockEntryDetailFormSet(rebuilt, prefix="items")
    return render(
        request, "backoffice/inventory/stock_entry_form.html#detail_items_partial", {"detail_formset": formset}
    )


@login_required
def stock_entry_detail(request: HttpRequest, pk: int) -> HttpResponse:
    entry = get_object_or_404(StockEntry, pk=pk)
    items = entry.items.select_related("item", "source_warehouse", "target_warehouse").all()
    voucher_no = str(entry.pk)
    # stock_ledger_entries_for_voucher already adds select_related("item", "warehouse") centrally.
    ledger_entries = StockEntry.stock_ledger_entries_for_voucher(voucher_no)
    return render(
        request,
        "backoffice/inventory/stock_entry_detail.html",
        {"entry": entry, "items": items, "ledger_entries": ledger_entries},
    )


@login_required
@require_POST
def stock_entry_submit(request: HttpRequest, pk: int) -> HttpResponse:
    entry = get_object_or_404(StockEntry, pk=pk)
    if entry.status == "DRAFT":
        try:
            entry.submit()
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return redirect("inventory:stock_entry_detail", pk=pk)


@login_required
@require_POST
def stock_entry_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    entry = get_object_or_404(StockEntry, pk=pk)
    if entry.status == "SUBMITTED":
        try:
            entry.cancel()
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return redirect("inventory:stock_entry_detail", pk=pk)


# ---------------------------------------------------------------------------
# StockReconciliation
# ---------------------------------------------------------------------------


@login_required
def reconciliation_list(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status")
    reason = request.GET.get("reason")
    warehouse_id = request.GET.get("warehouse")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    reconciliations = StockReconciliation.objects.select_related("warehouse").all()
    if status:
        reconciliations = reconciliations.filter(status=status)
    if reason:
        reconciliations = reconciliations.filter(reason=reason)
    if warehouse_id:
        reconciliations = reconciliations.filter(warehouse_id=warehouse_id)
    if date_from:
        reconciliations = reconciliations.filter(posting_date__gte=date_from)
    if date_to:
        reconciliations = reconciliations.filter(posting_date__lte=date_to)
    return render(
        request,
        "backoffice/inventory/reconciliation_list.html",
        {
            "reconciliations": reconciliations,
            "warehouses": Warehouse.objects.filter(disabled=False),
            "reason_choices": StockReconciliation._meta.get_field("reason").choices,
            "selected_status": status,
            "selected_reason": reason,
            "selected_warehouse": warehouse_id,
            "date_from": date_from or "",
            "date_to": date_to or "",
        },
    )


@login_required
def reconciliation_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = StockReconciliationForm(request.POST)
        item_fs = StockReconciliationItemFormSet(request.POST, instance=StockReconciliation(), prefix="items")
        if form.is_valid() and item_fs.is_valid():
            with transaction.atomic():
                reconciliation = form.save()
                item_fs.instance = reconciliation
                item_fs.save()
            return redirect("inventory:reconciliation_detail", pk=reconciliation.pk)
    else:
        form = StockReconciliationForm()
        item_fs = StockReconciliationItemFormSet(instance=StockReconciliation(), prefix="items")
    return render(
        request,
        "backoffice/inventory/reconciliation_form.html",
        {"form": form, "is_create": True, "item_formset": item_fs, "show_errors": True},
    )


@login_required
@require_POST
def reconciliation_item_add(request: HttpRequest) -> HttpResponse:
    post_data = request.POST.copy()
    total_forms = int(post_data.get("items-TOTAL_FORMS", 0))

    empty_form = StockReconciliationItemFormSet(prefix="items").empty_form
    line_fields = list(empty_form.fields.keys())
    pk_field = empty_form._meta.model._meta.pk.name
    if pk_field not in line_fields:
        line_fields.append(pk_field)

    for field in line_fields:
        post_data[f"items-{total_forms}-{field}"] = ""

    post_data["items-TOTAL_FORMS"] = total_forms + 1

    formset = StockReconciliationItemFormSet(post_data, prefix="items")
    return render(request, "backoffice/inventory/reconciliation_form.html#items_partial", {"item_formset": formset})


@login_required
@require_POST
def reconciliation_item_remove(request: HttpRequest, index: int) -> HttpResponse:
    post_data = request.POST.copy()
    total_forms = int(post_data.get("items-TOTAL_FORMS", 0))

    empty_form = StockReconciliationItemFormSet(prefix="items").empty_form
    line_fields = list(empty_form.fields.keys())
    pk_field = empty_form._meta.model._meta.pk.name
    if pk_field not in line_fields:
        line_fields.append(pk_field)

    new_data = {}
    new_index = 0

    for i in range(total_forms):
        if i == index:
            continue
        for field in line_fields:
            new_data[f"items-{new_index}-{field}"] = post_data.get(f"items-{i}-{field}", "")
        new_index += 1

    new_data["items-TOTAL_FORMS"] = new_index
    new_data["items-INITIAL_FORMS"] = post_data.get("items-INITIAL_FORMS", 0)
    new_data["items-MIN_NUM_FORMS"] = post_data.get("items-MIN_NUM_FORMS", 0)
    new_data["items-MAX_NUM_FORMS"] = post_data.get("items-MAX_NUM_FORMS", 1000)

    encoded = urllib.parse.urlencode(new_data, doseq=True)
    rebuilt = QueryDict(encoded, mutable=True)

    formset = StockReconciliationItemFormSet(rebuilt, prefix="items")
    return render(request, "backoffice/inventory/reconciliation_form.html#items_partial", {"item_formset": formset})


@login_required
def reconciliation_detail(request: HttpRequest, pk: int) -> HttpResponse:
    reconciliation = get_object_or_404(
        StockReconciliation.objects.select_related("warehouse"),
        pk=pk,
    )
    items = reconciliation.items.select_related("item").all()
    voucher_no = str(pk)
    ledger_entries = StockLedgerEntry.objects.filter(
        voucher_type="Stock Reconciliation", voucher_no=voucher_no
    ).select_related("item", "warehouse")
    return render(
        request,
        "backoffice/inventory/reconciliation_detail.html",
        {
            "reconciliation": reconciliation,
            "items": items,
            "ledger_entries": ledger_entries,
        },
    )


@login_required
@require_POST
def reconciliation_submit(request: HttpRequest, pk: int) -> HttpResponse:
    reconciliation = get_object_or_404(StockReconciliation, pk=pk)
    if reconciliation.status == "DRAFT":
        try:
            reconciliation.submit()
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return redirect("inventory:reconciliation_detail", pk=pk)


@login_required
@require_POST
def reconciliation_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    reconciliation = get_object_or_404(StockReconciliation, pk=pk)
    if reconciliation.status == "SUBMITTED":
        try:
            reconciliation.cancel()
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return redirect("inventory:reconciliation_detail", pk=pk)


# ---------------------------------------------------------------------------
# PurchaseReceipt
# ---------------------------------------------------------------------------


@login_required
def purchase_receipt_list(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status")
    supplier = request.GET.get("supplier")
    receipts = PurchaseReceipt.objects.select_related("warehouse").all()
    if status:
        receipts = receipts.filter(status=status)
    if supplier:
        receipts = receipts.filter(supplier_name__icontains=supplier)
    return render(
        request,
        "backoffice/inventory/purchase_receipt_list.html",
        {
            "receipts": receipts,
            "selected_status": status,
            "selected_supplier": supplier or "",
        },
    )


@login_required
def purchase_receipt_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = PurchaseReceiptForm(request.POST)
        item_fs = PurchaseReceiptItemFormSet(request.POST, instance=PurchaseReceipt(), prefix="items")
        if form.is_valid() and item_fs.is_valid():
            with transaction.atomic():
                receipt = form.save()
                item_fs.instance = receipt
                item_fs.save()
            return redirect("inventory:purchase_receipt_detail", pk=receipt.pk)
    else:
        form = PurchaseReceiptForm()
        item_fs = PurchaseReceiptItemFormSet(instance=PurchaseReceipt(), prefix="items")
    return render(
        request,
        "backoffice/inventory/purchase_receipt_form.html",
        {"form": form, "is_create": True, "item_formset": item_fs, "show_errors": True},
    )


@login_required
@require_POST
def purchase_receipt_item_add(request: HttpRequest) -> HttpResponse:
    post_data = request.POST.copy()
    total_forms = int(post_data.get("items-TOTAL_FORMS", 0))

    empty_form = PurchaseReceiptItemFormSet(prefix="items").empty_form
    line_fields = list(empty_form.fields.keys())
    pk_field = empty_form._meta.model._meta.pk.name
    if pk_field not in line_fields:
        line_fields.append(pk_field)

    for field in line_fields:
        post_data[f"items-{total_forms}-{field}"] = ""

    post_data["items-TOTAL_FORMS"] = total_forms + 1

    formset = PurchaseReceiptItemFormSet(post_data, prefix="items")
    return render(request, "backoffice/inventory/purchase_receipt_form.html#items_partial", {"item_formset": formset})


@login_required
@require_POST
def purchase_receipt_item_remove(request: HttpRequest, index: int) -> HttpResponse:
    post_data = request.POST.copy()
    total_forms = int(post_data.get("items-TOTAL_FORMS", 0))

    empty_form = PurchaseReceiptItemFormSet(prefix="items").empty_form
    line_fields = list(empty_form.fields.keys())
    pk_field = empty_form._meta.model._meta.pk.name
    if pk_field not in line_fields:
        line_fields.append(pk_field)

    new_data = {}
    new_index = 0

    for i in range(total_forms):
        if i == index:
            continue
        for field in line_fields:
            new_data[f"items-{new_index}-{field}"] = post_data.get(f"items-{i}-{field}", "")
        new_index += 1

    new_data["items-TOTAL_FORMS"] = new_index
    new_data["items-INITIAL_FORMS"] = post_data.get("items-INITIAL_FORMS", 0)
    new_data["items-MIN_NUM_FORMS"] = post_data.get("items-MIN_NUM_FORMS", 0)
    new_data["items-MAX_NUM_FORMS"] = post_data.get("items-MAX_NUM_FORMS", 1000)

    encoded = urllib.parse.urlencode(new_data, doseq=True)
    rebuilt = QueryDict(encoded, mutable=True)

    formset = PurchaseReceiptItemFormSet(rebuilt, prefix="items")
    return render(request, "backoffice/inventory/purchase_receipt_form.html#items_partial", {"item_formset": formset})


@login_required
def purchase_receipt_detail(request: HttpRequest, pk: int) -> HttpResponse:
    receipt = get_object_or_404(
        PurchaseReceipt.objects.select_related("warehouse"),
        pk=pk,
    )
    items = receipt.items.select_related("item", "item__stock_uom").all()
    voucher_no = str(pk)
    ledger_entries = StockLedgerEntry.objects.filter(
        voucher_type="Purchase Receipt", voucher_no=voucher_no
    ).select_related("item", "warehouse")
    return render(
        request,
        "backoffice/inventory/purchase_receipt_detail.html",
        {"receipt": receipt, "items": items, "ledger_entries": ledger_entries},
    )


@login_required
@require_POST
def purchase_receipt_submit(request: HttpRequest, pk: int) -> HttpResponse:
    # select_related("warehouse") saves one FK fetch inside receipt.submit().
    receipt = get_object_or_404(PurchaseReceipt.objects.select_related("warehouse"), pk=pk)
    if receipt.status == "DRAFT":
        try:
            receipt.submit()
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return redirect("inventory:purchase_receipt_detail", pk=pk)


@login_required
@require_POST
def purchase_receipt_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    receipt = get_object_or_404(PurchaseReceipt.objects.select_related("warehouse"), pk=pk)
    if receipt.status == "SUBMITTED":
        try:
            receipt.cancel()
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
    return redirect("inventory:purchase_receipt_detail", pk=pk)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@login_required
def stock_ledger_list(request: HttpRequest) -> HttpResponse:
    item_id = request.GET.get("item")
    warehouse_id = request.GET.get("warehouse")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    entries = StockLedgerEntry.objects.select_related("item", "warehouse").all()
    if item_id:
        entries = entries.filter(item_id=item_id)
    if warehouse_id:
        entries = entries.filter(warehouse_id=warehouse_id)
    if date_from:
        entries = entries.filter(posting_datetime__date__gte=date_from)
    if date_to:
        entries = entries.filter(posting_datetime__date__lte=date_to)
    items = Item.objects.all().order_by("item_name")
    warehouses = Warehouse.objects.all().order_by("name")
    return render(
        request,
        "backoffice/inventory/stock_ledger_list.html",
        {
            "entries": entries,
            "items": items,
            "warehouses": warehouses,
            "selected_item": item_id,
            "selected_warehouse": warehouse_id,
            "date_from": date_from or "",
            "date_to": date_to or "",
        },
    )


@login_required
def stock_balance_list(request: HttpRequest) -> HttpResponse:
    warehouse_id = request.GET.get("warehouse")
    bins = Bin.objects.select_related("item", "warehouse").all()
    if warehouse_id:
        bins = bins.filter(warehouse_id=warehouse_id)
    warehouses = Warehouse.objects.all().order_by("name")
    return render(
        request,
        "backoffice/inventory/stock_balance_list.html",
        {
            "bins": bins,
            "warehouses": warehouses,
            "selected_warehouse": warehouse_id,
        },
    )

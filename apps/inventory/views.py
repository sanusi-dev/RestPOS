from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.settings.models import Branch

from .forms import (
    BatchForm,
    ItemBarcodeFormSet,
    ItemForm,
    ItemGroupForm,
    ItemUOMConversionFormSet,
    ProductBundleForm,
    ProductBundleItemFormSet,
    PurchaseReceiptForm,
    PurchaseReceiptItemFormSet,
    ReorderLevelFormSet,
    StockEntryDetailFormSet,
    StockEntryForm,
    StockReconciliationForm,
    StockReconciliationItemFormSet,
    UOMForm,
    WarehouseForm,
)
from .models import (
    UOM,
    Batch,
    Bin,
    Item,
    ItemGroup,
    ProductBundle,
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
        "warehouse_count": Warehouse.objects.count(),
        "uom_count": UOM.objects.count(),
        "batch_count": Batch.objects.count(),
        "bundle_count": ProductBundle.objects.count(),
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
    roots = ItemGroup.objects.filter(parent__isnull=True).prefetch_related("children").order_by("name")
    return render(request, "backoffice/inventory/item_group_list.html", {"roots": roots})


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
    children = group.children.all().order_by("name")
    items = group.items.all().order_by("item_name")
    return render(
        request,
        "backoffice/inventory/item_group_detail.html",
        {"group": group, "children": children, "items": items},
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
    branch_id = request.GET.get("branch")
    warehouses = Warehouse.objects.select_related("branch", "parent").all()
    if branch_id:
        warehouses = warehouses.filter(branch_id=branch_id)
    branches = Branch.objects.all().order_by("name")
    return render(
        request,
        "backoffice/inventory/warehouse_list.html",
        {"warehouses": warehouses, "branches": branches, "selected_branch": branch_id},
    )


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
    warehouse = get_object_or_404(Warehouse.objects.select_related("branch", "parent"), pk=pk)
    children = warehouse.children.all().order_by("name")
    bins = warehouse.bins.select_related("item").order_by("item__item_name")
    return render(
        request,
        "backoffice/inventory/warehouse_detail.html",
        {"warehouse": warehouse, "children": children, "bins": bins},
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
    item_group_id = request.GET.get("item_group")
    department = request.GET.get("department")
    items = Item.objects.select_related("item_group", "stock_uom", "default_warehouse").all()
    if item_group_id:
        items = items.filter(item_group_id=item_group_id)
    if department:
        items = items.filter(department=department)
    item_groups = ItemGroup.objects.all().order_by("name")
    return render(
        request,
        "backoffice/inventory/item_list.html",
        {
            "items": items,
            "item_groups": item_groups,
            "selected_item_group": item_group_id,
            "selected_department": department,
        },
    )


@login_required
def item_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES)
        barcode_fs = ItemBarcodeFormSet(request.POST, instance=Item())
        uom_fs = ItemUOMConversionFormSet(request.POST, instance=Item())
        reorder_fs = ReorderLevelFormSet(request.POST, instance=Item())
        if form.is_valid() and barcode_fs.is_valid() and uom_fs.is_valid() and reorder_fs.is_valid():
            item = form.save()
            barcode_fs.instance = item
            barcode_fs.save()
            uom_fs.instance = item
            uom_fs.save()
            reorder_fs.instance = item
            reorder_fs.save()
            return redirect("inventory:item_detail", pk=item.pk)
    else:
        form = ItemForm()
        barcode_fs = ItemBarcodeFormSet(instance=Item())
        uom_fs = ItemUOMConversionFormSet(instance=Item())
        reorder_fs = ReorderLevelFormSet(instance=Item())
    return render(
        request,
        "backoffice/inventory/item_form.html",
        {
            "form": form,
            "is_create": True,
            "barcode_formset": barcode_fs,
            "uom_formset": uom_fs,
            "reorder_formset": reorder_fs,
        },
    )


@login_required
def item_detail(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(
        Item.objects.select_related("item_group", "stock_uom", "default_warehouse", "variant_of"),
        pk=pk,
    )
    barcodes = item.barcodes.all()
    uom_conversions = item.uom_conversions.select_related("uom").all()
    reorder_levels = item.reorder_levels.select_related("warehouse").all()
    bins = item.bins.select_related("warehouse").all()
    return render(
        request,
        "backoffice/inventory/item_detail.html",
        {
            "item": item,
            "barcodes": barcodes,
            "uom_conversions": uom_conversions,
            "reorder_levels": reorder_levels,
            "bins": bins,
        },
    )


@login_required
def item_update(request: HttpRequest, pk: int) -> HttpResponse:
    item = get_object_or_404(Item, pk=pk)
    if request.method == "POST":
        form = ItemForm(request.POST, request.FILES, instance=item)
        barcode_fs = ItemBarcodeFormSet(request.POST, instance=item)
        uom_fs = ItemUOMConversionFormSet(request.POST, instance=item)
        reorder_fs = ReorderLevelFormSet(request.POST, instance=item)
        if form.is_valid() and barcode_fs.is_valid() and uom_fs.is_valid() and reorder_fs.is_valid():
            form.save()
            barcode_fs.save()
            uom_fs.save()
            reorder_fs.save()
            return redirect("inventory:item_detail", pk=item.pk)
    else:
        form = ItemForm(instance=item)
        barcode_fs = ItemBarcodeFormSet(instance=item)
        uom_fs = ItemUOMConversionFormSet(instance=item)
        reorder_fs = ReorderLevelFormSet(instance=item)
    return render(
        request,
        "backoffice/inventory/item_form.html",
        {
            "form": form,
            "is_create": False,
            "item": item,
            "barcode_formset": barcode_fs,
            "uom_formset": uom_fs,
            "reorder_formset": reorder_fs,
        },
    )


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


@login_required
def batch_list(request: HttpRequest) -> HttpResponse:
    item_id = request.GET.get("item")
    batches = Batch.objects.select_related("item").all()
    if item_id:
        batches = batches.filter(item_id=item_id)
    items = Item.objects.filter(has_batch_no=True).order_by("item_name")
    return render(
        request,
        "backoffice/inventory/batch_list.html",
        {"batches": batches, "items": items, "selected_item": item_id},
    )


@login_required
def batch_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = BatchForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("inventory:batch_list")
    else:
        form = BatchForm()
    return render(
        request,
        "backoffice/inventory/batch_form.html",
        {"form": form, "is_create": True},
    )


@login_required
def batch_detail(request: HttpRequest, pk: int) -> HttpResponse:
    batch = get_object_or_404(Batch.objects.select_related("item"), pk=pk)
    return render(request, "backoffice/inventory/batch_detail.html", {"batch": batch})


@login_required
def batch_update(request: HttpRequest, pk: int) -> HttpResponse:
    batch = get_object_or_404(Batch, pk=pk)
    if request.method == "POST":
        form = BatchForm(request.POST, instance=batch)
        if form.is_valid():
            form.save()
            return redirect("inventory:batch_detail", pk=batch.pk)
    else:
        form = BatchForm(instance=batch)
    return render(
        request,
        "backoffice/inventory/batch_form.html",
        {"form": form, "is_create": False, "batch": batch},
    )


# ---------------------------------------------------------------------------
# ProductBundle
# ---------------------------------------------------------------------------


@login_required
def product_bundle_list(request: HttpRequest) -> HttpResponse:
    bundles = ProductBundle.objects.select_related("parent_item").all()
    return render(
        request,
        "backoffice/inventory/product_bundle_list.html",
        {"bundles": bundles},
    )


@login_required
def product_bundle_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ProductBundleForm(request.POST)
        item_fs = ProductBundleItemFormSet(request.POST, instance=ProductBundle())
        if form.is_valid() and item_fs.is_valid():
            bundle = form.save()
            item_fs.instance = bundle
            item_fs.save()
            return redirect("inventory:product_bundle_detail", pk=bundle.pk)
    else:
        form = ProductBundleForm()
        item_fs = ProductBundleItemFormSet(instance=ProductBundle())
    return render(
        request,
        "backoffice/inventory/product_bundle_form.html",
        {"form": form, "is_create": True, "item_formset": item_fs},
    )


@login_required
def product_bundle_detail(request: HttpRequest, pk: int) -> HttpResponse:
    bundle = get_object_or_404(ProductBundle.objects.select_related("parent_item"), pk=pk)
    items = bundle.items.select_related("item").all()
    return render(
        request,
        "backoffice/inventory/product_bundle_detail.html",
        {"bundle": bundle, "items": items},
    )


@login_required
def product_bundle_update(request: HttpRequest, pk: int) -> HttpResponse:
    bundle = get_object_or_404(ProductBundle, pk=pk)
    if request.method == "POST":
        form = ProductBundleForm(request.POST, instance=bundle)
        item_fs = ProductBundleItemFormSet(request.POST, instance=bundle)
        if form.is_valid() and item_fs.is_valid():
            form.save()
            item_fs.save()
            return redirect("inventory:product_bundle_detail", pk=bundle.pk)
    else:
        form = ProductBundleForm(instance=bundle)
        item_fs = ProductBundleItemFormSet(instance=bundle)
    return render(
        request,
        "backoffice/inventory/product_bundle_form.html",
        {"form": form, "is_create": False, "bundle": bundle, "item_formset": item_fs},
    )


# ---------------------------------------------------------------------------
# StockEntry
# ---------------------------------------------------------------------------


@login_required
def stock_entry_list(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status")
    purpose = request.GET.get("purpose")
    entries = StockEntry.objects.select_related("from_warehouse", "to_warehouse").all()
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
        detail_fs = StockEntryDetailFormSet(request.POST, instance=StockEntry())
        if form.is_valid() and detail_fs.is_valid():
            entry = form.save()
            detail_fs.instance = entry
            detail_fs.save()
            return redirect("inventory:stock_entry_detail", pk=entry.pk)
    else:
        form = StockEntryForm()
        detail_fs = StockEntryDetailFormSet(instance=StockEntry())
    return render(
        request,
        "backoffice/inventory/stock_entry_form.html",
        {"form": form, "is_create": True, "detail_formset": detail_fs},
    )


@login_required
def stock_entry_detail(request: HttpRequest, pk: int) -> HttpResponse:
    entry = get_object_or_404(
        StockEntry.objects.select_related("from_warehouse", "to_warehouse"),
        pk=pk,
    )
    items = entry.items.select_related("item", "uom", "source_warehouse", "target_warehouse").all()
    voucher_no = str(entry.pk)
    ledger_entries = StockEntry.stock_ledger_entries_for_voucher(voucher_no).select_related("item", "warehouse")
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
        entry.submit()
    return redirect("inventory:stock_entry_detail", pk=pk)


@login_required
@require_POST
def stock_entry_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    entry = get_object_or_404(StockEntry, pk=pk)
    if entry.status == "SUBMITTED":
        entry.cancel()
    return redirect("inventory:stock_entry_detail", pk=pk)


# ---------------------------------------------------------------------------
# StockReconciliation
# ---------------------------------------------------------------------------


@login_required
def reconciliation_list(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status")
    reconciliations = StockReconciliation.objects.select_related("warehouse").all()
    if status:
        reconciliations = reconciliations.filter(status=status)
    return render(
        request,
        "backoffice/inventory/reconciliation_list.html",
        {"reconciliations": reconciliations, "selected_status": status},
    )


@login_required
def reconciliation_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = StockReconciliationForm(request.POST)
        item_fs = StockReconciliationItemFormSet(request.POST, instance=StockReconciliation())
        if form.is_valid() and item_fs.is_valid():
            reconciliation = form.save()
            item_fs.instance = reconciliation
            item_fs.save()
            return redirect("inventory:reconciliation_detail", pk=reconciliation.pk)
    else:
        form = StockReconciliationForm()
        item_fs = StockReconciliationItemFormSet(instance=StockReconciliation())
    return render(
        request,
        "backoffice/inventory/reconciliation_form.html",
        {"form": form, "is_create": True, "item_formset": item_fs},
    )


@login_required
def reconciliation_detail(request: HttpRequest, pk: int) -> HttpResponse:
    reconciliation = get_object_or_404(
        StockReconciliation.objects.select_related("warehouse"),
        pk=pk,
    )
    items = reconciliation.items.select_related("item", "warehouse").all()
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
        reconciliation.submit()
    return redirect("inventory:reconciliation_detail", pk=pk)


@login_required
@require_POST
def reconciliation_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    reconciliation = get_object_or_404(StockReconciliation, pk=pk)
    if reconciliation.status == "SUBMITTED":
        reconciliation.cancel()
    return redirect("inventory:reconciliation_detail", pk=pk)


# ---------------------------------------------------------------------------
# PurchaseReceipt
# ---------------------------------------------------------------------------


@login_required
def purchase_receipt_list(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status")
    supplier = request.GET.get("supplier")
    receipts = PurchaseReceipt.objects.select_related("accepted_warehouse", "rejected_warehouse").all()
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
        item_fs = PurchaseReceiptItemFormSet(request.POST, instance=PurchaseReceipt())
        if form.is_valid() and item_fs.is_valid():
            receipt = form.save()
            item_fs.instance = receipt
            item_fs.save()
            return redirect("inventory:purchase_receipt_detail", pk=receipt.pk)
    else:
        form = PurchaseReceiptForm()
        item_fs = PurchaseReceiptItemFormSet(instance=PurchaseReceipt())
    return render(
        request,
        "backoffice/inventory/purchase_receipt_form.html",
        {"form": form, "is_create": True, "item_formset": item_fs},
    )


@login_required
def purchase_receipt_detail(request: HttpRequest, pk: int) -> HttpResponse:
    receipt = get_object_or_404(
        PurchaseReceipt.objects.select_related("accepted_warehouse", "rejected_warehouse"),
        pk=pk,
    )
    items = receipt.items.select_related("item", "uom", "batch", "warehouse").all()
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
    receipt = get_object_or_404(PurchaseReceipt, pk=pk)
    if receipt.status == "DRAFT":
        receipt.submit()
    return redirect("inventory:purchase_receipt_detail", pk=pk)


@login_required
@require_POST
def purchase_receipt_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    receipt = get_object_or_404(PurchaseReceipt, pk=pk)
    if receipt.status == "SUBMITTED":
        receipt.cancel()
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

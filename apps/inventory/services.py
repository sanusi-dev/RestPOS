"""Inventory document services — stock posting and reversal workflows."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Bin, Item, PurchaseReceipt, PurchaseReceiptItem, StockEntry, StockLedgerEntry, StockReconciliation

# ---------------------------------------------------------------------------
# Stock Entry
# ---------------------------------------------------------------------------


@transaction.atomic
def submit_stock_entry(entry):
    """Post the stock entry: create SLEs for every detail line and mark submitted."""
    from apps.settings.models import ProductionUnit, Restaurant

    locked = StockEntry.objects.select_for_update().get(pk=entry.pk)
    if locked.status != "DRAFT":
        entry.status = locked.status
        return
    restaurant = Restaurant.load()
    if not restaurant or not restaurant.store_warehouse_id or restaurant.store_warehouse.disabled:
        raise ValidationError("Configure an enabled central Store warehouse before submitting.")
    if locked.purpose not in {"MATERIAL_RECEIPT", "MATERIAL_TRANSFER"}:
        raise ValidationError("Unsupported stock entry purpose.")

    targets = {}
    if locked.purpose == "MATERIAL_TRANSFER":
        # Store is the only source; FOOD flows to the Kitchen unit's
        # warehouse and DRINKS to the Bar / POS sales warehouse.
        if not restaurant.default_warehouse_id or restaurant.default_warehouse.disabled:
            raise ValidationError("Configure an enabled Bar / POS sales warehouse before transferring stock.")
        units = {
            unit.department: unit
            for unit in ProductionUnit.objects.select_related("warehouse").filter(
                department__in=[ProductionUnit.FOOD, ProductionUnit.DRINKS]
            )
        }
        food_unit = units.get(ProductionUnit.FOOD)
        drinks_unit = units.get(ProductionUnit.DRINKS)
        if not food_unit or food_unit.warehouse.disabled:
            raise ValidationError("Configure an enabled Kitchen production unit warehouse before transferring stock.")
        if (
            not drinks_unit
            or drinks_unit.warehouse.disabled
            or drinks_unit.warehouse_id != restaurant.default_warehouse_id
        ):
            raise ValidationError("Configure the Drinks production unit to use the enabled Bar / POS sales warehouse.")
        if (
            restaurant.store_warehouse_id
            in {
                restaurant.default_warehouse_id,
                food_unit.warehouse_id,
            }
            or restaurant.default_warehouse_id == food_unit.warehouse_id
        ):
            raise ValidationError("Store, Kitchen, and Bar warehouses must be distinct.")
        targets = {"FOOD": food_unit.warehouse, "DRINKS": restaurant.default_warehouse}

    details = list(locked.items.select_related("item", "source_warehouse", "target_warehouse"))
    if not details:
        raise ValidationError("Add at least one item before submitting.")
    for detail in details:
        detail.validate_for_submission(restaurant=restaurant, targets=targets)

    bin_keys = {
        (detail.item_id, warehouse_id)
        for detail in details
        for warehouse_id in (
            [restaurant.store_warehouse_id]
            if locked.purpose == "MATERIAL_RECEIPT"
            else [restaurant.store_warehouse_id, targets[detail.item.department].pk]
        )
    }
    for item_id, warehouse_id in sorted(bin_keys):
        Bin.get_or_create_bin_id(item_id, warehouse_id)
    # Stable lock ordering prevents two multi-line documents from
    # deadlocking while they update FIFO state for shared bins.
    locked_bins = {
        (bin_obj.item_id, bin_obj.warehouse_id): bin_obj
        for bin_obj in Bin.objects.select_for_update()
        .filter(
            item_id__in=[item_id for item_id, _ in bin_keys],
            warehouse_id__in=[warehouse_id for _, warehouse_id in bin_keys],
        )
        .order_by("item_id", "warehouse_id")
    }

    voucher_no = str(locked.pk)
    updated_items = set()
    for detail in details:
        store_bin = locked_bins[(detail.item_id, restaurant.store_warehouse_id)]
        if locked.purpose == "MATERIAL_RECEIPT":
            detail.source_warehouse = None
            detail.target_warehouse = restaurant.store_warehouse
            StockLedgerEntry._create_entry_locked(
                item=detail.item,
                warehouse=restaurant.store_warehouse,
                actual_qty=detail.qty,
                voucher_type="Stock Entry",
                voucher_no=voucher_no,
                rate=detail.basic_rate,
                voucher_detail_no=str(detail.pk),
                prevent_negative=False,
                bin_obj=store_bin,
            )
            # Receipts carry the purchase rate into the item's last-buy
            # price so downstream transfers are valued at cost.
            detail.item.last_purchase_rate = detail.basic_rate
            updated_items.add(detail.item)
        else:
            target = targets[detail.item.department]
            detail.source_warehouse = restaurant.store_warehouse
            detail.target_warehouse = target
            outgoing = StockLedgerEntry._create_entry_locked(
                item=detail.item,
                warehouse=restaurant.store_warehouse,
                actual_qty=-detail.qty,
                voucher_type="Stock Entry",
                voucher_no=voucher_no,
                rate=Decimal("0"),
                voucher_detail_no=str(detail.pk),
                prevent_negative=True,
                bin_obj=store_bin,
            )
            # The transfer-in is valued at the outgoing FIFO rate so
            # the store's cost follows the goods into the unit.
            StockLedgerEntry._create_entry_locked(
                item=detail.item,
                warehouse=target,
                actual_qty=detail.qty,
                voucher_type="Stock Entry",
                voucher_no=voucher_no,
                rate=outgoing.outgoing_rate,
                voucher_detail_no=str(detail.pk),
                prevent_negative=False,
                bin_obj=locked_bins[(detail.item_id, target.pk)],
            )
        detail.save(update_fields=["source_warehouse", "target_warehouse", "updated_at"])
    if updated_items:
        Item.objects.bulk_update(updated_items, ["last_purchase_rate", "updated_at"])
    locked.status = "SUBMITTED"
    locked.save(update_fields=["status", "updated_at"])
    entry.status = locked.status


@transaction.atomic
def cancel_stock_entry(entry):
    """Reverse every SLE created by this entry and mark cancelled."""
    locked = StockEntry.objects.select_for_update().get(pk=entry.pk)
    if locked.status != "SUBMITTED":
        entry.status = locked.status
        return
    voucher_no = str(locked.pk)
    _reverse_voucher(
        StockLedgerEntry.objects.filter(voucher_type="Stock Entry", voucher_no=voucher_no),
        voucher_type="Stock Entry",
        voucher_no=voucher_no,
    )
    locked.status = "CANCELLED"
    locked.save(update_fields=["status", "updated_at"])
    entry.status = locked.status


# ---------------------------------------------------------------------------
# Stock Reconciliation
# ---------------------------------------------------------------------------


@transaction.atomic
def submit_stock_reconciliation(reconciliation):
    """Post adjustment SLEs so each item's Bin matches the counted qty."""
    from apps.settings.models import ProductionUnit

    locked = StockReconciliation.objects.select_for_update().select_related("warehouse").get(pk=reconciliation.pk)
    if locked.status != "DRAFT":
        reconciliation.status = locked.status
        return
    if locked.warehouse.disabled:
        raise ValidationError("The reconciliation warehouse must be enabled.")
    valid_reasons = {value for value, _label in locked._meta.get_field("reason").choices}
    if locked.reason not in valid_reasons:
        raise ValidationError("A reconciliation reason is required.")

    lines = list(locked.items.select_related("item"))
    if not lines:
        raise ValidationError("Add at least one item before submitting.")
    for line in lines:
        if line.item.disabled or not line.item.is_stock_item or line.item.has_variants:
            raise ValidationError(f"{line.item.item_name} is not an enabled stock item.")
        if line.qty < 0:
            raise ValidationError(f"Counted quantity for {line.item.item_name} cannot be negative.")
    if locked.reason == "CONSUMPTION":
        # Consumption write-offs only make sense at the Kitchen
        # warehouse: that's where food stock is used up in cooking.
        kitchen = ProductionUnit.objects.select_related("warehouse").filter(department=ProductionUnit.FOOD).first()
        if not kitchen or kitchen.warehouse_id != locked.warehouse_id:
            raise ValidationError("Consumption reconciliation is only allowed for the configured Kitchen warehouse.")
        if any(line.item.department != "FOOD" for line in lines):
            raise ValidationError("Consumption reconciliation accepts FOOD stock items only.")

    for line in lines:
        Bin.get_or_create_bin_id(line.item_id, locked.warehouse_id)
    locked_bins = {
        bin_obj.item_id: bin_obj
        for bin_obj in Bin.objects.select_for_update()
        .filter(item_id__in=[line.item_id for line in lines], warehouse_id=locked.warehouse_id)
        .order_by("item_id")
    }
    voucher_no = str(locked.pk)
    for line in lines:
        bin_obj = locked_bins[line.item_id]
        current_qty = bin_obj.actual_qty
        if locked.purpose != "OPENING_STOCK" and line.qty < bin_obj.reserved_qty:
            # A physical count can never dip below what the POS has
            # promised to sell (open draft reservations).
            raise ValidationError(
                f"Counted quantity for {line.item.item_name} cannot be below reserved quantity "
                f"({bin_obj.reserved_qty})."
            )
        line.current_qty = current_qty
        line.save(update_fields=["current_qty", "updated_at"])
        difference = line.qty - current_qty
        if difference == 0:
            continue
        # Opening stock values the item at its configured rate; a
        # reconciliation posts at zero and relies on the existing
        # FIFO valuation.
        rate = line.valuation_rate if locked.purpose == "OPENING_STOCK" else Decimal("0")
        StockLedgerEntry._create_entry_locked(
            item=line.item,
            warehouse=locked.warehouse,
            actual_qty=difference,
            voucher_type="Stock Reconciliation",
            voucher_no=voucher_no,
            rate=rate or Decimal("0"),
            voucher_detail_no=str(line.pk),
            prevent_negative=False,
            bin_obj=bin_obj,
        )
    locked.status = "SUBMITTED"
    locked.save(update_fields=["status", "updated_at"])
    reconciliation.status = locked.status


@transaction.atomic
def cancel_stock_reconciliation(reconciliation):
    """Reverse every SLE created by this reconciliation and mark cancelled."""
    locked = StockReconciliation.objects.select_for_update().get(pk=reconciliation.pk)
    if locked.status != "SUBMITTED":
        reconciliation.status = locked.status
        return
    voucher_no = str(locked.pk)
    _reverse_voucher(
        StockLedgerEntry.objects.filter(voucher_type="Stock Reconciliation", voucher_no=voucher_no),
        voucher_type="Stock Reconciliation",
        voucher_no=voucher_no,
    )
    locked.status = "CANCELLED"
    locked.save(update_fields=["status", "updated_at"])
    reconciliation.status = locked.status


# ---------------------------------------------------------------------------
# Purchase Receipt
# ---------------------------------------------------------------------------


@transaction.atomic
def submit_purchase_receipt(receipt):
    """Post the receipt: create SLEs for each line into the configured store warehouse."""
    from apps.settings.models import Restaurant

    locked = PurchaseReceipt.objects.select_for_update().get(pk=receipt.pk)
    if locked.status != "DRAFT":
        receipt.status = locked.status
        return
    restaurant = Restaurant.load()
    if not restaurant or not restaurant.store_warehouse_id or restaurant.store_warehouse.disabled:
        raise ValidationError("Configure an enabled central Store warehouse before submitting.")
    if locked.warehouse_id and locked.warehouse_id != restaurant.store_warehouse_id:
        raise ValidationError("Purchase Receipt warehouse must be the configured central Store.")

    lines = list(locked.items.select_related("item"))
    if not lines:
        raise ValidationError("Add at least one item before submitting.")
    for line in lines:
        line.validate_for_submission()
        Bin.get_or_create_bin_id(line.item_id, restaurant.store_warehouse_id)
    locked_bins = {
        bin_obj.item_id: bin_obj
        for bin_obj in Bin.objects.select_for_update()
        .filter(item_id__in=[line.item_id for line in lines], warehouse_id=restaurant.store_warehouse_id)
        .order_by("item_id")
    }
    total = Decimal("0")
    updated_items = set()
    for line in lines:
        StockLedgerEntry._create_entry_locked(
            item=line.item,
            warehouse=restaurant.store_warehouse,
            actual_qty=line.received_qty,
            voucher_type="Purchase Receipt",
            voucher_no=str(locked.pk),
            rate=line.rate,
            voucher_detail_no=str(line.pk),
            prevent_negative=False,
            bin_obj=locked_bins[line.item_id],
        )
        line.item.last_purchase_rate = line.rate
        updated_items.add(line.item)
        total += line.amount
    Item.objects.bulk_update(updated_items, ["last_purchase_rate", "updated_at"])
    locked.warehouse = restaurant.store_warehouse
    locked.total = total
    locked.status = "SUBMITTED"
    locked.save(update_fields=["warehouse", "status", "total", "updated_at"])
    receipt.warehouse = locked.warehouse
    receipt.total = locked.total
    receipt.status = locked.status


@transaction.atomic
def cancel_purchase_receipt(receipt):
    """Reverse every SLE created by this receipt and mark cancelled."""
    locked = PurchaseReceipt.objects.select_for_update().get(pk=receipt.pk)
    if locked.status != "SUBMITTED":
        receipt.status = locked.status
        return
    voucher_no = str(locked.pk)
    _reverse_voucher(
        StockLedgerEntry.objects.filter(voucher_type="Purchase Receipt", voucher_no=voucher_no),
        voucher_type="Purchase Receipt",
        voucher_no=voucher_no,
    )
    _revert_last_purchase_rates(locked)
    locked.status = "CANCELLED"
    locked.save(update_fields=["status", "updated_at"])
    receipt.status = locked.status


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _reverse_voucher(queryset, *, voucher_type, voucher_no):
    """Reverse every non-cancelled SLE of a voucher and mark the rows cancelled."""
    sles = list(queryset.select_for_update().exclude(is_cancelled=True).select_related("item", "warehouse"))
    if not sles:
        return
    bin_keys = {(sle.item_id, sle.warehouse_id) for sle in sles}
    locked_bins = {
        (bin_obj.item_id, bin_obj.warehouse_id): bin_obj
        for bin_obj in Bin.objects.select_for_update()
        .filter(
            item_id__in=[item_id for item_id, _ in bin_keys],
            warehouse_id__in=[warehouse_id for _, warehouse_id in bin_keys],
        )
        .order_by("item_id", "warehouse_id")
    }
    for sle in sles:
        StockLedgerEntry._create_entry_locked(
            item=sle.item,
            warehouse=sle.warehouse,
            actual_qty=-sle.actual_qty,
            voucher_type=f"{voucher_type} Cancellation",
            voucher_no=voucher_no,
            rate=sle.outgoing_rate if sle.actual_qty < 0 else Decimal("0"),
            voucher_detail_no=sle.voucher_detail_no,
            prevent_negative=sle.actual_qty > 0,
            bin_obj=locked_bins[(sle.item_id, sle.warehouse_id)],
        )
        sle.is_cancelled = True
        sle.save(update_fields=["is_cancelled", "updated_at"])


def _revert_last_purchase_rates(receipt):
    # select_related("item") avoids per-line FK fetch. We keep the per-line prior-rate
    # lookup (FIFO queue tail is intentionally per item) but combine the writes into
    # a single bulk_update at the end instead of one UPDATE per line.
    lines = list(receipt.items.select_related("item").all())
    if not lines:
        return
    items_to_update = []
    for line in lines:
        prior = (
            PurchaseReceiptItem.objects.filter(
                item=line.item,
                purchase_receipt__status="SUBMITTED",
            )
            .exclude(purchase_receipt=receipt)
            .select_related("purchase_receipt")
            .order_by("-purchase_receipt__posting_date", "-purchase_receipt__pk")
            .first()
        )
        line.item.last_purchase_rate = prior.rate if prior else None
        items_to_update.append(line.item)
    Item.objects.bulk_update(items_to_update, ["last_purchase_rate", "updated_at"])

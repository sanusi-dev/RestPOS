"""Inventory document services — WAC posting and reversal workflows."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    Bin,
    Item,
    ItemGroup,
    PurchaseReceipt,
    PurchaseReceiptItem,
    StockEntry,
    StockEntryDetail,
    StockLedgerEntry,
    StockReconciliation,
)


def _resolve_account(account, label):
    if account is None:
        raise ValidationError(f"{label} is not configured.")
    if account.disabled:
        raise ValidationError(f"{label} ({account.name}) is disabled.")
    if not account.is_leaf:
        raise ValidationError(f"{label} ({account.name}) must be a leaf account.")
    return account


def _expense_account_for(item_group, default_expense):
    if item_group is not None and getattr(item_group, "expense_account_id", None):
        return item_group.expense_account
    return default_expense


def _post_gl_rows(posting_date, voucher_type, voucher_no, rows, remarks):
    """Merge rows per account and post via GLEntry."""

    from apps.accounting.models import GLEntry

    if not rows:
        return []
    merged = {}
    for r in rows:
        key = r["account"].pk
        if key in merged:
            merged[key]["debit"] = merged[key].get("debit", Decimal("0")) + r.get("debit", Decimal("0"))
            merged[key]["credit"] = merged[key].get("credit", Decimal("0")) + r.get("credit", Decimal("0"))
        else:
            merged[key] = dict(r)
    out = list(merged.values())
    against = ", ".join(r["account"].name for r in out if r.get("credit"))
    for r in out:
        r.setdefault("against", against)
    return GLEntry.post(
        posting_date=posting_date,
        rows=out,
        voucher_type=voucher_type,
        voucher_no=voucher_no,
        remarks=remarks,
    )


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

    details = list(locked.items.select_related("item", "item__item_group", "source_warehouse", "target_warehouse"))
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
    gl_rows = []
    default_expense = restaurant.default_expense_account if restaurant else None
    # H3: bulk fetch ItemGroups for MATERIAL_RECEIPT
    groups = {}
    if locked.purpose == "MATERIAL_RECEIPT":
        group_ids = {d.item.item_group_id for d in details if getattr(d.item, "item_group_id", None)}
        if group_ids:
            groups = {g.pk: g for g in ItemGroup.objects.select_related("expense_account").filter(pk__in=group_ids)}
    for detail in details:
        store_bin = locked_bins[(detail.item_id, restaurant.store_warehouse_id)]
        if locked.purpose == "MATERIAL_RECEIPT":
            detail.source_warehouse = None
            detail.target_warehouse = restaurant.store_warehouse
            StockLedgerEntry._create_entry_locked(
                item=detail.item,
                warehouse=restaurant.store_warehouse,
                quantity=detail.qty,
                voucher_type="Stock Entry",
                voucher_no=voucher_no,
                unit_rate=detail.basic_rate,
                voucher_detail_no=str(detail.pk),
                prevent_negative=False,
                posting_date=locked.posting_date,
                bin_obj=store_bin,
            )
            detail.item.last_purchase_rate = detail.basic_rate
            updated_items.add(detail.item)
            # GL: Dr SIH / Cr Expense (market purchase, no GRNI)
            if detail.basic_rate and detail.qty:
                sih_account = _resolve_account(restaurant.store_warehouse.account, "The Store warehouse account")
                group = groups.get(detail.item.item_group_id) if getattr(detail.item, "item_group_id", None) else None
                if group is None:
                    group = getattr(detail.item, "item_group", None)
                expense_acct = _expense_account_for(group, default_expense)
                expense_acct = _resolve_account(expense_acct, "The default expense account")
                amount = (detail.qty * detail.basic_rate).quantize(Decimal("0.01"))
                if amount:
                    gl_rows.append({"account": sih_account, "debit": amount})
                    gl_rows.append({"account": expense_acct, "credit": amount})
        else:
            target = targets[detail.item.department]
            detail.source_warehouse = restaurant.store_warehouse
            detail.target_warehouse = target
            outgoing = StockLedgerEntry._create_entry_locked(
                item=detail.item,
                warehouse=restaurant.store_warehouse,
                quantity=-detail.qty,
                voucher_type="Stock Entry",
                voucher_no=voucher_no,
                unit_rate=None,
                voucher_detail_no=str(detail.pk),
                prevent_negative=True,
                posting_date=locked.posting_date,
                bin_obj=store_bin,
            )
            StockLedgerEntry._create_entry_locked(
                item=detail.item,
                warehouse=target,
                quantity=detail.qty,
                voucher_type="Stock Entry",
                voucher_no=voucher_no,
                unit_rate=outgoing.unit_rate,
                voucher_detail_no=str(detail.pk),
                prevent_negative=False,
                posting_date=locked.posting_date,
                bin_obj=locked_bins[(detail.item_id, target.pk)],
            )
        detail.save(update_fields=["source_warehouse", "target_warehouse", "updated_at"])
    if updated_items:
        Item.objects.bulk_update(updated_items, ["last_purchase_rate", "updated_at"])
    if gl_rows and locked.purpose == "MATERIAL_RECEIPT":
        _post_gl_rows(
            locked.posting_date,
            "Stock Entry",
            voucher_no,
            gl_rows,
            f"Stock Entry {voucher_no} MATERIAL_RECEIPT",
        )
    locked.status = "SUBMITTED"
    locked.save(update_fields=["status", "updated_at"])
    entry.status = locked.status


@transaction.atomic
def cancel_stock_entry(entry):
    """Reverse every SLE created by this entry and mark cancelled."""
    from apps.accounting.models import GLEntry

    locked = StockEntry.objects.select_for_update().get(pk=entry.pk)
    if locked.status != "SUBMITTED":
        entry.status = locked.status
        return
    voucher_no = str(locked.pk)
    original_sles = list(
        StockLedgerEntry.objects.select_related("item", "warehouse", "item__item_group").filter(
            voucher_type="Stock Entry", voucher_no=voucher_no
        )
    )
    if locked.purpose == "MATERIAL_TRANSFER":
        details = list(locked.items.select_related("item").all())
        from apps.settings.models import ProductionUnit, Restaurant

        restaurant = Restaurant.load()
        targets = {}
        if restaurant:
            units = {u.department: u for u in ProductionUnit.objects.all()}
            food_unit = units.get(ProductionUnit.FOOD)
            if food_unit:
                targets["FOOD"] = food_unit.warehouse
            if restaurant.default_warehouse_id:
                targets["DRINKS"] = restaurant.default_warehouse
        bin_keys = set()
        for d in details:
            bin_keys.add((d.item_id, restaurant.store_warehouse_id))
            tgt = targets.get(d.item.department)
            if tgt:
                bin_keys.add((d.item_id, tgt.pk if hasattr(tgt, "pk") else tgt))
        locked_bins = {
            (b.item_id, b.warehouse_id): b
            for b in Bin.objects.select_for_update()
            .filter(
                item_id__in=[k[0] for k in bin_keys],
                warehouse_id__in=[k[1] for k in bin_keys],
            )
            .order_by("item_id", "warehouse_id")
        }
        for detail in details:
            tgt = targets.get(detail.item.department)
            if not tgt:
                continue
            tgt_id = tgt.pk if hasattr(tgt, "pk") else tgt
            dest_bin = locked_bins.get((detail.item_id, tgt_id))
            store_bin = locked_bins.get((detail.item_id, restaurant.store_warehouse_id))
            if not dest_bin or not store_bin:
                continue
            dest_wac = dest_bin.valuation_rate or Decimal("0")
            orig_dest = next(
                (
                    s
                    for s in original_sles
                    if s.warehouse_id == tgt_id and s.quantity > 0 and s.voucher_detail_no == str(detail.pk)
                ),
                None,
            )
            orig_store = next(
                (
                    s
                    for s in original_sles
                    if s.warehouse_id == restaurant.store_warehouse_id
                    and s.quantity < 0
                    and s.voucher_detail_no == str(detail.pk)
                ),
                None,
            )
            StockLedgerEntry._create_entry_locked(
                item=detail.item,
                warehouse=tgt,
                quantity=-detail.qty,
                voucher_type="Stock Entry Cancellation",
                voucher_no=voucher_no,
                unit_rate=None,
                voucher_detail_no=str(detail.pk),
                prevent_negative=True,
                posting_date=locked.posting_date,
                reversal_of_sle_id=orig_dest.pk if orig_dest else None,
                bin_obj=dest_bin,
            )
            StockLedgerEntry._create_entry_locked(
                item=detail.item,
                warehouse=restaurant.store_warehouse,
                quantity=detail.qty,
                voucher_type="Stock Entry Cancellation",
                voucher_no=voucher_no,
                unit_rate=dest_wac,
                voucher_detail_no=str(detail.pk),
                prevent_negative=False,
                posting_date=locked.posting_date,
                reversal_of_sle_id=orig_store.pk if orig_store else None,
                bin_obj=store_bin,
            )
    else:
        from apps.settings.models import Restaurant

        restaurant = Restaurant.load()
        sles = original_sles
        if sles:
            bin_keys = {(s.item_id, s.warehouse_id) for s in sles}
            locked_bins = {
                (b.item_id, b.warehouse_id): b
                for b in Bin.objects.select_for_update()
                .filter(
                    item_id__in=[k[0] for k in bin_keys],
                    warehouse_id__in=[k[1] for k in bin_keys],
                )
                .order_by("item_id", "warehouse_id")
            }
            # H3: bulk fetch ItemGroups for expense lookup
            group_ids = {s.item.item_group_id for s in sles if getattr(s.item, "item_group_id", None)}
            groups = {}
            if group_ids:
                groups = {g.pk: g for g in ItemGroup.objects.select_related("expense_account").filter(pk__in=group_ids)}
            # C1: capture pre-reversal WAC before SLE reversal
            pre_wac_map = {}
            for sle in sles:
                bin_obj = locked_bins[(sle.item_id, sle.warehouse_id)]
                pre_wac = bin_obj.valuation_rate or Decimal("0")
                pre_wac_map[sle.pk] = pre_wac
                variance = sle.quantity * (pre_wac - sle.unit_rate)
                variance_type = "CANCELLATION_WAC" if variance != 0 else ""
                StockLedgerEntry._create_entry_locked(
                    item=sle.item,
                    warehouse=sle.warehouse,
                    quantity=-sle.quantity,
                    voucher_type="Stock Entry Cancellation",
                    voucher_no=voucher_no,
                    unit_rate=None,
                    voucher_detail_no=sle.voucher_detail_no,
                    prevent_negative=sle.quantity > 0,
                    posting_date=locked.posting_date,
                    variance_amount=variance,
                    variance_type=variance_type,
                    reversal_of_sle_id=sle.pk,
                    bin_obj=bin_obj,
                )
            # C2/C3/C4/H6: build GL uniformly per SLE using pre-reversal WAC
            gl_originals = list(
                GLEntry.objects.filter(voucher_type="Stock Entry", voucher_no=voucher_no, is_cancelled=False)
            )
            if gl_originals:
                for gl in gl_originals:
                    gl.is_cancelled = True
                    gl.save(update_fields=["is_cancelled", "updated_at"])
                # Determine if any drift exists to resolve variance account once (C3)
                has_drift = False
                for sle in sles:
                    pre_wac = pre_wac_map[sle.pk]
                    curr_amount = (sle.quantity * pre_wac).quantize(Decimal("0.01"))
                    orig_amount = (sle.quantity * sle.unit_rate).quantize(Decimal("0.01"))
                    if curr_amount != orig_amount:
                        has_drift = True
                        break
                variance_acct = None
                if has_drift:
                    variance_acct = _resolve_account(
                        restaurant.inventory_price_variance_account if restaurant else None,
                        "The inventory price variance account",
                    )
                new_rows = []
                for sle in sles:
                    pre_wac = pre_wac_map[sle.pk]
                    sih_acct = _resolve_account(sle.warehouse.account, "The warehouse account")
                    group = groups.get(sle.item.item_group_id) if getattr(sle.item, "item_group_id", None) else None
                    if group is None and getattr(sle.item, "item_group", None) is not None:
                        group = sle.item.item_group
                    exp_acct = _expense_account_for(group, restaurant.default_expense_account if restaurant else None)
                    exp_acct = _resolve_account(exp_acct, "The default expense account")
                    orig_amount = (sle.quantity * sle.unit_rate).quantize(Decimal("0.01"))
                    curr_amount = (sle.quantity * pre_wac).quantize(Decimal("0.01"))
                    new_rows.append({"account": sih_acct, "credit": curr_amount})
                    new_rows.append({"account": exp_acct, "debit": orig_amount})
                    diff = curr_amount - orig_amount
                    if diff != 0:
                        if variance_acct is None:
                            raise ValidationError("The inventory price variance account is not configured.")
                        if diff > 0:
                            new_rows.append({"account": variance_acct, "debit": diff})
                        else:
                            new_rows.append({"account": variance_acct, "credit": -diff})
                if new_rows:
                    _post_gl_rows(locked.posting_date, "Stock Entry", voucher_no, new_rows, "Reversal")
            # H4: revert last_purchase_rate for stock entry material receipt
            _revert_last_purchase_rates_for_stock_entry(locked, sles)
        # Also handle case where sles empty but still need to revert? No items.
        locked.status = "CANCELLED"
        locked.save(update_fields=["status", "updated_at"])
        entry.status = locked.status
        return
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

    lines = list(locked.items.select_related("item", "item__item_group"))
    if not lines:
        raise ValidationError("Add at least one item before submitting.")
    for line in lines:
        if line.item.disabled or not line.item.is_stock_item or line.item.has_variants:
            raise ValidationError(f"{line.item.item_name} is not an enabled stock item.")
        if line.qty < 0:
            raise ValidationError(f"Counted quantity for {line.item.item_name} cannot be negative.")
    if locked.reason == "CONSUMPTION":
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
    gl_rows = []
    from apps.settings.models import Restaurant

    restaurant = Restaurant.load()
    for line in lines:
        bin_obj = locked_bins[line.item_id]
        current_qty = bin_obj.actual_qty
        if locked.purpose != "OPENING_STOCK" and line.qty < bin_obj.reserved_qty:
            raise ValidationError(
                f"Counted quantity for {line.item.item_name} cannot be below reserved quantity "
                f"({bin_obj.reserved_qty})."
            )
        line.current_qty = current_qty
        line.save(update_fields=["current_qty", "updated_at"])
        difference = line.qty - current_qty
        if difference == 0:
            continue
        rate = None
        if locked.purpose == "OPENING_STOCK":
            if difference > 0:
                if line.valuation_rate is None:
                    raise ValidationError(f"Opening stock for {line.item.item_name} requires a valuation rate.")
                rate = line.valuation_rate
            else:
                rate = None
        else:
            if bin_obj.actual_qty == 0 and difference > 0:
                if line.valuation_rate is None:
                    raise ValidationError(
                        f"A valuation rate is required to seed empty stock for {line.item.item_name}."
                    )
                rate = line.valuation_rate
            else:
                rate = None

        # C5: capture WAC before SLE
        wac_before = bin_obj.valuation_rate or Decimal("0")
        StockLedgerEntry._create_entry_locked(
            item=line.item,
            warehouse=locked.warehouse,
            quantity=difference,
            voucher_type="Stock Reconciliation",
            voucher_no=voucher_no,
            unit_rate=rate,
            voucher_detail_no=str(line.pk),
            prevent_negative=False,
            posting_date=locked.posting_date,
            bin_obj=bin_obj,
        )
        if locked.reason == "WASTE_DAMAGE" and difference < 0:
            amount = (abs(difference) * wac_before).quantize(Decimal("0.01"))
            # H7: hoist restaurant guard before accessing wastage account
            if amount and restaurant is not None:
                wastage_acct = _resolve_account(restaurant.wastage_account, "The wastage account")
                sih_acct = _resolve_account(locked.warehouse.account, "The warehouse account")
                gl_rows.append({"account": wastage_acct, "debit": amount})
                gl_rows.append({"account": sih_acct, "credit": amount})
    if gl_rows:
        _post_gl_rows(
            locked.posting_date,
            "Stock Reconciliation",
            voucher_no,
            gl_rows,
            f"Stock Reconciliation {voucher_no} {locked.reason}",
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
    sles = list(
        StockLedgerEntry.objects.select_related("item", "warehouse").filter(
            voucher_type="Stock Reconciliation", voucher_no=voucher_no
        )
    )
    if sles:
        bin_keys = {(s.item_id, s.warehouse_id) for s in sles}
        locked_bins = {
            (b.item_id, b.warehouse_id): b
            for b in Bin.objects.select_for_update()
            .filter(
                item_id__in=[k[0] for k in bin_keys],
                warehouse_id__in=[k[1] for k in bin_keys],
            )
            .order_by("item_id", "warehouse_id")
        }
        for sle in sles:
            bin_obj = locked_bins[(sle.item_id, sle.warehouse_id)]
            StockLedgerEntry._create_entry_locked(
                item=sle.item,
                warehouse=sle.warehouse,
                quantity=-sle.quantity,
                voucher_type="Stock Reconciliation Cancellation",
                voucher_no=voucher_no,
                unit_rate=None,
                voucher_detail_no=sle.voucher_detail_no,
                prevent_negative=sle.quantity > 0,
                posting_date=locked.posting_date,
                reversal_of_sle_id=sle.pk,
                bin_obj=bin_obj,
            )
        from apps.accounting.models import GLEntry

        # C6: only post if originals existed (is_cancelled=False); guard idempotent
        gl_rows = list(
            GLEntry.objects.filter(voucher_type="Stock Reconciliation", voucher_no=voucher_no, is_cancelled=False)
        )
        if gl_rows:
            for gl in gl_rows:
                gl.is_cancelled = True
                gl.save(update_fields=["is_cancelled", "updated_at"])
            GLEntry.post(
                posting_date=locked.posting_date,
                rows=[
                    {
                        "account": gl.account,
                        "debit": gl.credit,
                        "credit": gl.debit,
                        "against": gl.against,
                    }
                    for gl in gl_rows
                ],
                voucher_type="Stock Reconciliation",
                voucher_no=voucher_no,
                remarks="Reversal",
            )
    locked.status = "CANCELLED"
    locked.save(update_fields=["status", "updated_at"])
    reconciliation.status = locked.status


# ---------------------------------------------------------------------------
# Purchase Receipt
# ---------------------------------------------------------------------------


def check_receipt_cancel_blocked(receipt):
    """Return True if receipt has downstream SUBMITTED invoice or allocated payment."""
    from apps.accounting.models import SupplierInvoice

    return SupplierInvoice.objects.filter(status=SupplierInvoice.SUBMITTED, purchase_receipt=receipt).exists()


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
    if not restaurant.stock_received_but_not_billed_account_id:
        raise ValidationError("Configure the stock received but not billed (GRNI) account before submitting.")
    if not restaurant.store_warehouse.account_id:
        raise ValidationError("Configure the Store warehouse account before submitting.")

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
            quantity=line.received_qty,
            voucher_type="Purchase Receipt",
            voucher_no=str(locked.pk),
            unit_rate=line.rate,
            voucher_detail_no=str(line.pk),
            prevent_negative=False,
            posting_date=locked.posting_date,
            bin_obj=locked_bins[line.item_id],
        )
        line.item.last_purchase_rate = line.rate
        updated_items.add(line.item)
        total += line.amount
    Item.objects.bulk_update(updated_items, ["last_purchase_rate", "updated_at"])
    from apps.accounting.models import GLEntry

    grni_acct = _resolve_account(
        restaurant.stock_received_but_not_billed_account, "The stock received but not billed account"
    )
    sih_acct = _resolve_account(restaurant.store_warehouse.account, "The Store warehouse account")
    stock_total = sum((line.amount for line in lines), Decimal("0")).quantize(Decimal("0.01"))
    if stock_total:
        GLEntry.post(
            posting_date=locked.posting_date,
            rows=[
                {"account": sih_acct, "debit": stock_total, "against": grni_acct.name},
                {"account": grni_acct, "credit": stock_total, "against": sih_acct.name},
            ],
            voucher_type="Purchase Receipt",
            voucher_no=str(locked.pk),
            remarks=f"Purchase Receipt {locked.pk}",
        )
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
    from apps.accounting.models import GLEntry
    from apps.settings.models import Restaurant

    locked = PurchaseReceipt.objects.select_for_update().get(pk=receipt.pk)
    if locked.status != "SUBMITTED":
        receipt.status = locked.status
        return
    if check_receipt_cancel_blocked(locked):
        raise ValidationError("Cancel the supplier invoice(s) and payment(s) for this receipt first.")
    voucher_no = str(locked.pk)
    sles = list(
        StockLedgerEntry.objects.select_related("item", "warehouse").filter(
            voucher_type="Purchase Receipt", voucher_no=voucher_no
        )
    )
    if not sles:
        _revert_last_purchase_rates(locked)
        locked.status = "CANCELLED"
        locked.save(update_fields=["status", "updated_at"])
        receipt.status = locked.status
        return
    restaurant = Restaurant.load()
    bin_keys = {(s.item_id, s.warehouse_id) for s in sles}
    locked_bins = {
        (b.item_id, b.warehouse_id): b
        for b in Bin.objects.select_for_update()
        .filter(
            item_id__in=[k[0] for k in bin_keys],
            warehouse_id__in=[k[1] for k in bin_keys],
        )
        .order_by("item_id", "warehouse_id")
    }
    # C1: capture pre-reversal WAC before SLE reversal
    pre_wac_map = {}
    for sle in sles:
        bin_obj = locked_bins[(sle.item_id, sle.warehouse_id)]
        pre_wac = bin_obj.valuation_rate or Decimal("0")
        pre_wac_map[sle.pk] = pre_wac
        variance = sle.quantity * (pre_wac - sle.unit_rate)
        variance_type = "CANCELLATION_WAC" if variance != 0 else ""
        StockLedgerEntry._create_entry_locked(
            item=sle.item,
            warehouse=sle.warehouse,
            quantity=-sle.quantity,
            voucher_type="Purchase Receipt Cancellation",
            voucher_no=voucher_no,
            unit_rate=None,
            voucher_detail_no=sle.voucher_detail_no,
            prevent_negative=True,
            posting_date=locked.posting_date,
            variance_amount=variance,
            variance_type=variance_type,
            reversal_of_sle_id=sle.pk,
            bin_obj=bin_obj,
        )
    # C2/C3/C4/H6: build GL uniformly using pre-reversal WAC
    gl_originals = list(
        GLEntry.objects.filter(voucher_type="Purchase Receipt", voucher_no=voucher_no, is_cancelled=False)
    )
    if gl_originals:
        for gl in gl_originals:
            gl.is_cancelled = True
            gl.save(update_fields=["is_cancelled", "updated_at"])
        grni_acct = _resolve_account(
            restaurant.stock_received_but_not_billed_account,
            "The stock received but not billed account",
        )
        has_drift = False
        for sle in sles:
            pre_wac = pre_wac_map[sle.pk]
            curr_amount = (sle.quantity * pre_wac).quantize(Decimal("0.01"))
            orig_amount = (sle.quantity * sle.unit_rate).quantize(Decimal("0.01"))
            if curr_amount != orig_amount:
                has_drift = True
                break
        variance_acct = None
        if has_drift:
            variance_acct = _resolve_account(
                restaurant.inventory_price_variance_account,
                "The inventory price variance account",
            )
        new_rows = []
        for sle in sles:
            pre_wac = pre_wac_map[sle.pk]
            curr_amount = (sle.quantity * pre_wac).quantize(Decimal("0.01"))
            orig_amount = (sle.quantity * sle.unit_rate).quantize(Decimal("0.01"))
            sih_acct = _resolve_account(sle.warehouse.account, "The warehouse account")
            new_rows.append({"account": sih_acct, "credit": curr_amount})
            new_rows.append({"account": grni_acct, "debit": orig_amount})
            diff = curr_amount - orig_amount
            if diff != 0:
                if variance_acct is None:
                    raise ValidationError("The inventory price variance account is not configured.")
                if diff > 0:
                    new_rows.append({"account": variance_acct, "debit": diff})
                else:
                    new_rows.append({"account": variance_acct, "credit": -diff})
        if new_rows:
            _post_gl_rows(locked.posting_date, "Purchase Receipt", voucher_no, new_rows, "Reversal")
    _revert_last_purchase_rates(locked)
    locked.status = "CANCELLED"
    locked.save(update_fields=["status", "updated_at"])
    receipt.status = locked.status


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _revert_last_purchase_rates(receipt):
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


def _revert_last_purchase_rates_for_stock_entry(entry, sles):
    """Revert last_purchase_rate for stock entry material receipt cancel."""
    if not sles:
        return
    seen = set()
    items_to_update = []
    for sle in sles:
        if sle.item_id in seen:
            continue
        seen.add(sle.item_id)
        prior = (
            StockEntryDetail.objects.filter(
                item_id=sle.item_id,
                stock_entry__status="SUBMITTED",
                stock_entry__purpose="MATERIAL_RECEIPT",
            )
            .exclude(stock_entry=entry)
            .select_related("stock_entry")
            .order_by("-stock_entry__posting_date", "-stock_entry__pk")
            .first()
        )
        sle.item.last_purchase_rate = prior.basic_rate if prior else None
        items_to_update.append(sle.item)
    if items_to_update:
        Item.objects.bulk_update(items_to_update, ["last_purchase_rate", "updated_at"])

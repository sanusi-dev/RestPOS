# Inventory Code Walkthrough — PWAC (Perpetual Weighted-Average Cost)

This document describes the inventory system on `feat/pwac-inventory-costing` after the FIFO → PWAC cutover. It answers the same sixteen questions as the previous FIFO audit, now for WAC.

> Scope: `apps/inventory`, `apps/settings`, `apps/orders`, `apps/accounting`, `apps/reports`. The ledger is the audit; the Bin is the truth; WAC is the only rate.

---

## 1. Architecture

| Component | What it is | Why it exists |
|---|---|---|
| `StockLedgerEntry` (SLE) | Append-only audit row per movement: `quantity` (signed), `unit_rate` (rate of THIS movement), `stock_value_change`, `variance_*`, `reversal_of_sle`, `posting_date`, `posting_datetime` | Records how the Bin changed; never edited |
| `Bin` | Current truth per item+warehouse: `actual_qty`, `valuation_rate` (= WAC), `reserved_qty` | Fast reads for POS, balances; `stock_value` is derived (`qty × WAC`) |
| `StockEntry` / `StockEntryDetail` | Draft container for receipts and Store→unit transfers | DRAFT → SUBMITTED → CANCELLED |
| `PurchaseReceipt` / `PurchaseReceiptItem` | Draft for supplier deliveries into Store | Same workflow; receipt rate blends WAC |
| `StockReconciliation` | Count adjustment (opening, physical, consumption, waste, correction) | Lets a count override the Bin |
| `Order` / `OrderItem` | POS orders reserve drink stock via `Bin.reserved_qty` | Prevents oversell before settlement |
| Services (`inventory/services.py`, `orders/services.py`) | Only production writers of SLE | Enforce status, locks, WAC |

No FIFO queue, no `stock_queue`, no `stock_value` stored on Bin or SLE.

---

## 2. WAC formula

Per `item + warehouse` Bin:

```
new_qty = old_qty + qty
if qty > 0:  # inbound at actual
    new_wac = (old_qty*old_wac + qty*actual) / new_qty
    value_change = qty*actual
else if qty < 0:  # outbound at current WAC
    value_change = qty*old_wac   # negative
    wac unchanged
```

Posting date is informational; valuation always at current WAC at `posting_datetime`.

---

## 3. SLE model

`apps/inventory/models.py:StockLedgerEntry`

| Field | Meaning |
|---|---|
| `item`, `warehouse` | scope |
| `posting_date` | business date (copy of voucher), editable=False, future dates rejected |
| `posting_datetime` | auto_now_add, ordering |
| `voucher_type/no/detail_no` | back-reference |
| `quantity` | signed |
| `unit_rate` | this movement's rate (inbound=actual, outbound=current WAC) |
| `stock_value_change` | signed `qty × unit_rate` |
| `variance_amount/type` | `CANCELLATION_WAC` or `SALE_RETURN`, else 0/blank |
| `reversal_of_sle` | FK self, SET_NULL, audit link |

Indexes: `(item, warehouse, -posting_datetime)`. No `is_cancelled`; cancellation creates a reversal SLE.

Immutability: rows never edited; `reversal_of_sle` links the reversal.

---

## 4. Bin

`apps/inventory/models.py:Bin`

| Field | Meaning |
|---|---|
| `actual_qty` | current qty |
| `valuation_rate` | current WAC |
| `reserved_qty` | draft drink promises (POS) |

`stock_value` is a `@property` (`qty × WAC`). Created lazily; updated only inside `_create_entry_locked`.

---

## 5. Posting choke point

All movements go through `StockLedgerEntry._create_entry_locked()` inside one `transaction.atomic()` with `select_for_update` on Bin. It blends WAC, writes SLE, updates Bin. `create_entry()` is the public wrapper that locks the Bin.

Future-dated `posting_date` is rejected; negative stock raises `InsufficientStock` (subclass of `ValidationError`) and rolls back with no SLE.

---

## 6. Flows

### Purchase Receipt
`submit_purchase_receipt()` → per line SLE `+qty @ rate` (blends Store WAC) + `Item.last_purchase_rate` + GL `Dr SIH / Cr GRNI` at receipt rate. `posting_date = receipt.posting_date`.

### Stock Entry MATERIAL_RECEIPT
Same SLE as receipt, into Store at `basic_rate`. GL `Dr SIH / Cr expense` (item-group expense → default) at same rate. No GRNI.

### Stock Entry MATERIAL_TRANSFER
Source `-qty @ source WAC` (outbound, WAC unchanged), dest `+qty @ source WAC` (blends dest WAC). Two SLEs, net zero. No GL. Targets: FOOD→Kitchen, DRINKS→Bar.

### Stock Reconciliation
`difference = counted − actual`. If `difference == 0` skip. Rate:
- `OPENING_STOCK` and `+qty` into empty Bin → require `valuation_rate` to seed WAC.
- Otherwise at current WAC (`unit_rate=None`).

`WASTE_DAMAGE` with `difference < 0` also posts GL `Dr wastage / Cr SIH` at current WAC.

### POS drink settlement
`_convert_drink_reservations()` → per drink line SLE `-qty @ current WAC` (WAC unchanged) + `reserved_qty` released. GL via `post_order_gl()` posts COGS at same WAC (`_cogs_legs` reads SLE `unit_rate`).

### POS return
`_restore_stock()` → per restockable drink `+qty @ current WAC` (identity blend, WAC unchanged) with `variance_amount = qty*(current_wac − original_wac)` and `variance_type=SALE_RETURN`. GL in `post_refund_gl()` reverses COGS at current WAC (`_current_wac_for_return` reads restore SLE or Bin) and, if `not_restockable`, posts wastage at current WAC.

---

## 7. Cancellation

No `is_cancelled` flag. Each document's cancel creates reversal SLEs with `reversal_of_sle` set and `voucher_type="… Cancellation"`, at current WAC.

- **Purchase Receipt**: blocked if a `SupplierInvoice(status=SUBMITTED, purchase_receipt=receipt)` exists (D6). Otherwise per line reversal `-qty @ current WAC`, `variance = qty*(current_wac − original_rate)`, `CANCELLATION_WAC`. GL `Cr SIH @ current WAC / Dr GRNI @ original` plus variance to `inventory_price_variance_account` (diff).

- **Stock Entry transfer**: dest `-qty @ dest current WAC`, source `+qty @ dest current WAC` (source blends at dest rate, net zero). No GL, no variance.

- **Stock Entry receipt**: reversal `-qty @ current WAC` with variance like purchase receipt, GL `Cr SIH / Dr expense` plus variance.

- **Stock Reconciliation**: reversal `-difference @ current WAC`, GL reversal for waste if any.

All reversals are inside `transaction.atomic()`; insufficient stock rolls back.

---

## 8. GL

| Document | Legs |
|---|---|
| Purchase Receipt submit | `Dr SIH (warehouse account) / Cr GRNI` @ `qty×rate` |
| Purchase Receipt cancel | `Cr SIH @ current WAC / Dr GRNI @ original` + variance → `inventory_price_variance_account` |
| Stock Entry receipt submit | `Dr SIH / Cr expense` @ `qty×rate` |
| Stock Entry receipt cancel | `Cr SIH @ current WAC / Dr expense @ original` + variance |
| Stock Entry transfer | none (net zero) |
| Stock Reconciliation waste | `Dr wastage / Cr SIH` @ `qty×WAC` |
| Supplier Invoice (stock, linked) | `Dr GRNI / Cr payable` @ same rate (rate equality enforced) |
| Supplier Invoice (expense) | `Dr expense / Cr payable` |
| Order settle | COGS `Dr expense / Cr SIH` at WAC |

---

## 9. Payables

`SupplierInvoice` stock lines must link via `purchase_receipt`; invoice posts to GRNI, clearing the receipt's GRNI. Rate and qty must equal the receipt line (backend `clean()`). Expense lines post to expense even when receipt-linked. Supplier payments allocate to outstanding invoices; receipt cancel is blocked while a submitted invoice or allocated payment exists.

---

## 10. Reports and accounting reads

- `_cogs_legs()` and `drink_cogs()` read SLE `quantity`/`unit_rate` (WAC), not FIFO layers.
- `kitchen_consumption()` reads reconciliation SLEs at WAC.
- `_wastage_rate()` prefers restore SLE `unit_rate`, then source order WAC, then Bin WAC.

---

## 11. Concurrency and guards

All writers lock Bins with `select_for_update` in deterministic order. Negative stock is prohibited. Future `posting_date` rejected. `reserved_qty` guards prevent a count below open promises.

---

## 12. Mental model

> Bin = current truth (WAC is the only rate). SLE = append-only audit of how that truth changed, at current WAC. Every transaction is a state transition against the current Bin; business dates don't affect valuation. Wastage and sale-return drifts are the only variances: receipt cancellations to the variance account, sale returns to COGS (SAP MAP behaviour).

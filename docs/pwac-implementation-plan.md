# PWAC Implementation Plan — FIFO → Perpetual Weighted-Average Cost

**Branch:** `feat/pwac-inventory-costing`
**Source doc:** `prompt.md` (solidified 2026-05-11, §§1-23 + D1-D8) + `docs/inventory-code-walkthrough.md` (current FIFO audit)
**Status:** Decision-locked, ready for build. Transcribe decision-only excerpt to `PLAN.md §4` on kickoff.

---

## 1. Context

RestPOS runs FIFO today. Every `StockLedgerEntry` carries a serialized `stock_queue [[qty, rate], …]` and every outbound consumes oldest layers. `Bin` mirrors `actual_qty / valuation_rate / stock_value`. The engine is centralized in `StockLedgerEntry._create_entry_locked` (`apps/inventory/models.py:302-403`) — 7 write paths funnel there. Current state is audited in `docs/inventory-code-walkthrough.md`.

Target is **Perpetual Weighted-Average Cost (PWAC):**

> `StockBin` = current truth (`wac` is the only rate). `SLE` = append-only audit of how that state changed. Costing always uses current WAC at `created_at`.

This eliminates FIFO queue, layer lookups, and historical snapshots. No replay.

---

## 2. Target Inventory Model

**Per `Item + Warehouse`:** one `StockBin`

```text
StockBin
  item_id, warehouse_id
  actual_qty (= quantity)
  valuation_rate (= wac)
  reserved_qty (unchanged, POS drinks)
  // stock_value removed — derived as actual_qty × valuation_rate
  // stock_queue removed
```

Invariant: `valuation_rate = wac`. `actual_qty >= 0`. Negative stock prohibited. Stock value is never stored; computed when needed (`qty × wac`).

**SLE (append-only, lean):**

```text
item, warehouse
voucher_type, voucher_no, voucher_detail_no
posting_date (business date, copy of voucher posting_date)
quantity (signed, replaces actual_qty)
unit_rate (rate of THIS movement: inbound=actual rate, outbound=current WAC)
stock_value_change (signed, qty × unit_rate)
variance_amount (0 unless cancellation WAC drift or sale-return COGS diff)
variance_type (CANCELLATION_WAC | SALE_RETURN — no PURCHASE_PRICE)
reversal_of_sle_id (FK, nullable — replaces is_cancelled mutation)
posting_datetime (auto_now_add)
```

Dropped: `stock_queue`, `incoming_rate`, `outgoing_rate`, `valuation_rate` (snapshot), `stock_value` (snapshot), `qty_after_transaction`, `wac_after`, `is_cancelled`. Hunt all callers; `valuation_rate` on Bin stays as current WAC, not an SLE snapshot.

---

## 3. Date Semantics

- `posting_date` on `PurchaseReceipt / StockEntry / StockReconciliation`: business/audit date, user-editable, informational only. No valuation effect.
- `created_at` / `posting_datetime` on SLE: when it entered system. System always blends at current WAC; there is no reorder, no replay, no special treatment for early dates. If user enters `posting_date` early, system still does normal WAC blend.

---

## 4. Locked Decisions D1–D8 (override draft §§6/14/22)

| ID | Decision | Rationale |
|---|---|---|
| D1 | **Backdated receipts = full WAC blend at actual cost.** Any receipt blends: `new_wac = (old_qty×old_wac + qty×actual)/ (old_qty+qty)`. No variance at receipt. | Simpler than Dynamics variance-at-receipt; `posting_date` is audit only. |
| D2 | **Wastage = no warehouse.** Keep `WASTE_DAMAGE` as `StockReconciliation.reason` on real warehouse, valued at current WAC → existing `Restaurant.wastage_account`. | ERPNext Material Issue practice. |
| D3 | **Opening stock entered rate seeds WAC.** `OPENING_STOCK` posts at user `valuation_rate`; if `Bin qty==0` and adjustment adds stock, require `valuation_rate` to seed WAC; else current WAC. | Handles zero-stock creation. |
| D4 | **GRN at receipt (accrual).** Receipt: `Dr SIH (warehouse asset) / Cr GRNI` @ receipt rate. Invoice *must* link to receipt via `SupplierInvoice.purchase_receipt`; invoice posts `Dr GRNI / Cr Payable` @ same rate. No unlinked `Dr SIH / Cr Payable` path — every receipt eventually invoiced at same rate. Random market purchase without formal receipt uses `StockEntry MATERIAL_RECEIPT` → `Dr SIH / Cr Cash-or-Expense` directly (no GRNI, no invoice). | Receipt is from supplier; rate locked equal (see D5). |
| D5 | **Dedicated variance account** `Restaurant.inventory_price_variance_account` for **cancellation WAC drift only**. Sale-return variance posts to **COGS** (not variance account): `variance = qty×(current WAC − original COGS rate)` → Dr COGS if positive, Cr COGS if negative. No `PURCHASE_PRICE` variance type — blocked, not bloated. | `PURCHASE_PRICE` never allowed (D4 rate lock). |
| D6 | **Block receipt cancel if downstream financial doc active** — `SupplierInvoice(status=SUBMITTED, purchase_receipt=receipt)` OR `SupplierPayment` allocation against that invoice. Cancel chain: `Payment → Invoice → Receipt`. | ERPNext `check_next_docstatus` extended to payments. |
| D7 | **Clean slate migration.** No production data. `RunPython` wipes `StockLedgerEntry` + `Bin` (FIFO snapshots) + drops `stock_value, stock_queue, is_cancelled, qty_after_transaction` columns. Docs stay; bins rebuild. | Dev data only. |
| D8 | **Backdated threshold** is report-only: `posting_date < created_at::date` labels "late entry" for humans; no valuation branch. | D1 corollary. |

---

## 5. Business Rules (final, §22 as locked)

| Event | Old date allowed? | Costing |
|---|---|---|
| Normal receipt | Yes | Normal WAC blend @ actual |
| Backdated receipt | Yes | Normal WAC blend @ actual (D1) |
| Sale / consumption | Prefer no | Current WAC |
| Waste (WASTE_DAMAGE) | Prefer no | Current WAC → wastage_account |
| Transfer | Prefer current | Source current WAC |
| Transfer cancellation | Yes, refs old voucher | Current dest WAC (plan §13) |
| External receipt cancellation | Yes | Current WAC; if downstream invoice/payment active → blocked per D6; if allowed, `Cr SIH @ current WAC / Dr GRNI @ original` → diff to variance (D5) |
| Sale cancellation/return | Yes | `+qty×current WAC` back to Bin; diff vs original COGS → Dr/Cr COGS (standard WAC return) |
| Reconciliation | Prefer current | Current WAC; if `qty==0` and `+qty` → require `valuation_rate` to seed |
| Future-dated tx | Reject | Validation `posting_date > today → reject` |

Conceptual rule: *Every tx is a state transition against current StockBin. SLE records `unit_rate` and `stock_value_change`. Business dates don't affect valuation.*

---

## 6. PWAC Formula

Inbound: `inbound_value = qty × actual`; `new_qty = old_qty + qty`; `new_wac = (old_qty×old_wac + inbound_value)/new_qty`.

Outbound: `cost = qty × current_wac`; `new_qty = old_qty − qty`; `wac` unchanged.
Example §4: 5 @ ₦100 (value implied) + 2 @ ₦150 → 7 qty, WAC ₦114.2857. Sale 5 @ WAC ₦120 → cost ₦600, Bin 15→10, WAC stays ₦120.

---

## 7. Specific Flows (from `prompt.md` §§5/8-14 as locked)

- **Normal/backdated receipt:** lock Bin, blend at actual, create SLE (`unit_rate=actual`, `stock_value_change=qty×actual`), post `Dr SIH / Cr GRNI`.
- **Sale/consumption/waste:** lock Bin, check `qty <= Bin.actual_qty` else `InsufficientStock`, `unit_rate=current_wac`, `stock_value_change=−qty×wac`, Bin qty↓, wac unchanged, SLE. Waste posts wastage_account via reconciliation GL; consumption strictly kitchen guard retained.
- **Negative stock:** prohibited everywhere. `raise ValidationError`, rollback, no SLE.
- **Transfer A→B:** source `−qty×source_wac`, dest `+qty×source_wac` then `new_wac = (old_qty×old_wac + transferred)/new_qty`, net 0.
- **Transfer cancel:** dest `−qty×dest_current_wac`, source `+qty×dest_current_wac` then source recalculates WAC, net 0.
- **Reconciliation:** `OPENING_STOCK` or `qty==0` + `+qty` → require entered `valuation_rate` to seed WAC; else at current WAC. `WASTE_DAMAGE`/`CONSUMPTION`/`PHYSICAL_COUNT`/`CORRECTION` at current WAC.
- **Receipt cancellation (D6):** if downstream invoice/payment active → block. Else: `Cr SIH @ current WAC / Dr GRNI @ original` → diff to `variance_amount` (`CANCELLATION_WAC`) → variance account. Reject if `qty > Bin.actual_qty`. No partial.
- **Sale cancellation/return (§11):** return adds `qty×current WAC`; diff vs original COGS posts to COGS (Dr if current WAC > original, Cr if <) — standard WAC, not variance account. `not_restockable` skip still posts wastage.

---

## 8. Current → Target Transition

### 8.1 What changes
- `Bin`: keep `actual_qty`, `valuation_rate (=wac)`, `reserved_qty`; **drop `stock_value`** (derived), drop `current_stock_queue()`. Compute `stock_value = actual_qty × valuation_rate` in code/views/reports when needed.
- `StockLedgerEntry`: **drop** `stock_queue`, `incoming_rate`, `outgoing_rate`, `valuation_rate`, `stock_value`, `qty_after_transaction`, `is_cancelled`; **add** `quantity`, `unit_rate`, `stock_value_change`, `variance_amount`, `variance_type`, `reversal_of_sle_id`, `posting_date`. `valuation_rate` meaning not reinterpreted — removed. Hunt: `apps/inventory/views.py`, `apps/reports/sources.py`, `apps/accounting/services.py:154-188` (`_cogs_legs`), admin, templates.
- `Restaurant`: add `stock_received_but_not_billed_account` (GRNI) + `inventory_price_variance_account` (cancellation drift). Seed defaults. Forms validate required when inventory active. Stock entry market purchase posts `Dr SIH / Cr Cash/Expense` — no GRNI.
- GL: receipt `Dr SIH / Cr GRNI`; linked invoice `Dr GRNI / Cr Payable` (rate equality enforced; no `amount_difference` to variance); unlinked stock-invoice path removed. Expense lines on invoice (`gas` etc.) → `Dr default-supplier-expense / Cr Payable` even when `purchase_receipt` linked — not a stock line, so not part of GRNI.

### 8.2 What stays
Document models, status `DRAFT/SUBMITTED/CANCELLED`, `select_for_update` locking, `reserved_qty` flow, warehouse topology, `Item.last_purchase_rate`, admin guards (SLE append-only via `reversal_of_sle_id`).

---

## 9. Detailed Implementation Plan

### Phase 1 — Settings & Chart (no inventory logic yet)
**Goal:** GRNI + variance accounts exist.
- **Files:** `apps/settings/models.py` (+ two FKs, `clean()`), `apps/settings/forms.py`, `apps/settings/admin.py`, `apps/accounting/management/commands/seed_chart_of_accounts.py` (GRNI liability + variance expense).
- **Tests:** settings form validates required accounts; seed creates accounts.
- **DoD:** `Restaurant.load().stock_received_but_not_billed_account` and `inventory_price_variance_account` selectable; `make migrate` clean.

### Phase 2 — Model Migration (schema + clean slate)
**Goal:** SLE/Bin WAC schema, no FIFO artifacts, no compatibility shims.
- **Files:** `apps/inventory/models.py` (Bin/SLE rewrite as §8.1), `apps/inventory/migrations/*` (schema + `RunPython` wipe: delete all `StockLedgerEntry` + reset `Bin.actual_qty/valuation_rate` to 0, drop `stock_value` column, clear queue JSON — dev data only per D7). Review destructive ops.
- **Tests:** migration on fresh DB + dev DB with dummy FIFO rows.
- **DoD:** No `stock_queue/stock_value/qty_after_transaction/is_cancelled/incoming/outgoing/valuation` on SLE; `reversal_of_sle_id` present; `Bin.stock_value` gone.

### Phase 3 — Core WAC Engine
**Goal:** Single source of truth.
- **Files:** `apps/inventory/models.py:302-403` (`_create_entry_locked` + `create_entry`):

  ```python
  current_qty = bin_obj.actual_qty or 0
  wac = bin_obj.valuation_rate or 0
  if quantity > 0:  # inbound
      inbound_value = quantity * unit_rate
      new_qty = current_qty + quantity
      new_wac = (current_qty * wac + inbound_value) / new_qty if new_qty else 0
      stock_value_change = inbound_value
      bin_obj.valuation_rate = new_wac
  elif quantity < 0:
      if current_qty + quantity < 0: raise ValidationError("Insufficient stock")
      stock_value_change = quantity * wac  # negative
      # wac unchanged
  else: pass
  bin_obj.actual_qty = current_qty + quantity
  # create SLE with quantity, unit_rate, stock_value_change, variance_amount/type, reversal_of_sle_id, posting_date
  ```

  Future-date guard (`posting_date > today → ValidationError`). No `qty_after_transaction/wac_after` writes. `reversal_of_sle_id` set on reversals, never mutate original.
- **Files:** `apps/inventory/admin.py` (expose new fields, immutability guard).
- **Tests:** `test_wac_engine.py` — inbound blends, outbound at current WAC, WAC unchanged, negative block, zero-qty, future-date reject, seed-from-zero requires rate.
- **DoD:** FIFO queue tests removed, WAC tests green.

### Phase 4 — Document Services + GL Hooks
**Goal:** Documents via WAC engine + GRN.
- **Files:** `apps/inventory/services.py` (`submit_purchase_receipt` posts `Dr SIH / Cr GRNI` @ `qty×rate`; `check_receipt_cancel_blocked` checks `SupplierInvoice` + `SupplierPayment` allocations; `_reverse_voucher` computes `variance_amount = qty×(current_wac − original_rate)` for cancellations → variance account; `submit_stock_entry` transfer at source WAC, dest recalculates; `submit_stock_reconciliation` at current WAC or entered rate if `qty==0`; `cancel_*` via `reversal_of_sle_id`).
- **Tests:** GRN posting, blocked cancel when downstream active, WAC transfer, reconciliation seed, wastage at current WAC → `wastage_account`.
- **DoD:** Receipt → Bin blends; transfer dest recalculates; cancel blocked when linked invoice/payment exists.

### Phase 5 — Payables Posting
**Goal:** Invoice clears GRNI at same rate.
- **Files:** `apps/accounting/services.py:568-616` (`post_supplier_invoice_gl`): if `invoice.purchase_receipt_id` → stock lines `Dr GRNI / Cr Payable` @ invoice amount (validated `== receipt rate`; no variance branch). Expense lines → `Dr Expense / Cr Payable` even when receipt linked. `cancel_supplier_invoice_gl` reverses via `_reverse_gl`.
- **Superseded by the receipt-first UX (see `docs/supplier-invoice-receipt-first-ux.md`):** stock lines are no longer user input — `build_supplier_invoice_stock_lines` creates `SupplierInvoiceItem` rows from the linked receipt's lines at submit (read-only thereafter); `SupplierInvoiceItemForm`/FormSet deleted; expenses are a dedicated `SupplierInvoiceExpense` (description + amount) posting `Dr Restaurant.default_supplier_expense_account / Cr Payable`, with a missing config a hard error at submit.
- **Tests:** linked invoice clears GRNI, expense line with receipt still `Dr Expense`; cancel reverses.
- **DoD:** Trial: receipt (SIH/GRNI) + linked invoice (GRNI/Payable) → SIH holds receipt value, GRNI 0.

### Phase 6 — Orders
**Goal:** Outbound at current WAC, no FIFO.
- **Files:** `apps/orders/services.py` (`_convert_drink_reservations` `prevent_negative=True` at current WAC; `_restore_stock` adds `+qty×current WAC`), `apps/reports/sources.py` (`_wastage_rate`, `drink_cogs`, `kitchen_consumption` read `unit_rate`/`stock_value_change` not FIFO layers), `apps/accounting/services.py:154-188` (`_cogs_legs` reads `unit_rate`).
- **Tests:** POS settlement at WAC, return `+qty×current WAC` diff → Dr/Cr COGS, consumption at WAC.
- **DoD:** Drink sale posts COGS at WAC.

### Phase 7 — Validation & Polish
- Backoffice SLE list/detail: show `quantity`, `unit_rate`, `stock_value_change`, `variance_amount/type`, `reversal_of_sle_id`; bin shows `actual_qty` and `valuation_rate` as WAC, `stock_value` computed (`qty×wac`) in view. `drink_stock_available = actual_qty − reserved_qty`.
- `make ruff`, `make test` full; smoke: receipt → GRN → invoice → GRNI 0 → sale → COGS → return → stock at current WAC.
- Docs: update `docs/inventory-code-walkthrough.md` to PWAC, `FEATURES.md` (PWAC, GRNI), retire FIFO sections.

### Phase 8 — Cutover
- Data wipe in Phase 2. Verify `Bin.actual_qty/valuation_rate` rebuild from new SLEs.
- Mark `PLAN.md §4` with D1-D8 + business rules + GL entries and close prompt.

---

## 10. Risks & Mitigations

- **Double SIH on receipt+invoice:** Mitigated by D4 lock — stock lines must link and rate equality enforced; GRNI prevents double `Dr SIH`.
- **GRNI left open:** Mitigated by D6 chain — receipt can't be cancelled with active invoice.
- **Negative stock race:** `select_for_update` retained; all outbound `prevent_negative=True`.
- **Queue JSON leftover:** Migration drops column; readers removed.

---

## 11. Acceptance Criteria

- [ ] No `stock_queue/qty_after_transaction/is_cancelled/incoming/outgoing/valuation(stock_value)` on SLE; no `Bin.stock_value`.
- [ ] Inbound blend: 5 @ ₦100 + 2 @ ₦150 → WAC ₦114.2857 (derived `stock_value = qty×wac`).
- [ ] Outbound leaves WAC unchanged; insufficient stock raises `InsufficientStock`.
- [ ] Receipt `Dr SIH / Cr GRNI`; linked invoice `Dr GRNI / Cr Payable` (rate equality enforced); stock-entry market purchase `Dr SIH / Cr Cash/Expense`.
- [ ] Receipt with active invoice/payment cannot be cancelled; allowed cancel `Cr SIH @ current WAC / Dr GRNI @ original` + `CANCELLATION_WAC` variance.
- [ ] Transfer at source WAC, dest recalculates; cancel at dest WAC, net 0.
- [ ] Sale return `+qty×current WAC` diff → Dr/Cr COGS (sale-return variance in COGS).
- [ ] `make test`, `make ruff` clean; `docs/` describes PWAC.

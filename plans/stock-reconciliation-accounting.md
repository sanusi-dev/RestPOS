# Stock Reconciliation — Reasons & Accounting Plan

Status: **Proposed — awaiting developer approval**

Applies to: `apps/inventory` (models, services, forms, views, templates), `apps/accounting`
(services), `apps/reports` (sources), `apps/settings` (Restaurant fields).

---

## 1. Problem statement

Stock Reconciliation currently has four reasons (`PHYSICAL_COUNT`, `CONSUMPTION`,
`WASTE_DAMAGE`, `CORRECTION`). Submitting one only posts signed-difference Stock Ledger
Entries — **nothing ever reaches the GL**. The FIFO cost of a shortage therefore leaves
Stock-in-Hand with no offsetting expense, and the balance sheet silently shrinks while the
P&L never sees the cost. There is no audit trail of which reason consumed which value
beyond the free-text SLE.

Additionally, two of the four reasons are redundant from an accounting standpoint, and one
(consumption) currently posts to the P&L via a hard-coded special case in the reports
module.

---

## 2. Reference review

### 2.1 ERPNext — Stock Reconciliation (`erpnext/stock/doctype/stock_reconciliation`)

**Reason taxonomy: none.** ERPNext has exactly two *purposes*:

| Purpose | GL treatment |
|---|---|
| `Opening Stock` | Difference account must be an **Asset/Liability** account — never P&L. |
| `Stock Reconciliation` | Difference account is the Company's `stock_adjustment_account` (P&L). |

The user-facing question ERPNext asks is not "why did stock change" but "is this the opening
balance or a correction". All correction types (wastage, damage, theft, counting error) go to
the **same** difference account; granularity lives in remarks/items, not accounts.

**GL posting mechanism (verified in `services/gl_composer.py` + `base_stock_gl_composer.py`):**

- The doctype carries a header-level `expense_account` ("Difference Account") and `cost_center`.
- On submit, `make_gl_entries()` → `StockReconciliationGLComposer.compose()` iterates the
  SLEs and, for each one, posts the pair:
  - `Stock-in-Hand` (warehouse's inventory account) ↔ `Difference Account`
  - debit/credit = `sle.stock_value_difference` (signed).
- Shortage → Dr Difference Account / Cr Stock-in-Hand.
  Surplus → Dr Stock-in-Hand / Cr Difference Account.
- The difference account defaults to `Company.stock_adjustment_account`
  (`get_difference_account()`), and cost center is mandatory for reconciliation.
- For `Opening Stock`, the difference account must be an Asset/Liability type account, so the
  opening balance never touches profit.
- **Cancel** reverses via the standard ERPNext GL reversal (mirrored rows).

**Stock Entry — Material Issue:** ERPNext's answer to consumption is a *Material Issue*
stock entry: Dr expense account (item default → item group default → Company
`stock_adjustment_account`) / Cr warehouse. That's how kitchen usage becomes a P&L expense
rather than a "reconciliation" — it is an expense event, not an inventory-count event.

### 2.2 URY

**No reconciliation accounting at all.** URY grants permissions to ERPNext's native Stock
Reconciliation doctype (default_permissions.py) and uses it as-is. Its daily P&L
(`ury_daily_p_and_l.py`) takes `materials_consumed` as a **manual table** — the user types
units consumed per material; nothing is auto-posted from stock or GL. URY never distinguishes
wastage/damage/consumption at the accounting layer.

### 2.3 Conclusion

- ERPNext does **not** cover reason-specific accounting. It collapses all corrections into
  one difference account and treats consumption as a separate *Material Issue* document type.
- URY covers **none** of it automatically.
- Therefore the four-reason taxonomy is a RestPOS invention with no industry precedent to
  copy — which is fine (it's a legitimate product requirement for a restaurant), but each
  reason must be given an explicit accounting treatment, because industry practice does not
  provide one.

---

## 3. Decision: reduce four reasons to three, with per-reason accounting

| Reason | Keep? | Accounting treatment |
|---|---|---|
| `CONSUMPTION` | **Keep** (only at Kitchen warehouse) | Dr `wastage_account` (Kitchen consumption) / Cr warehouse stock-in-hand, per line at FIFO rate. Feeds the Daily P&L Kitchen-consumption memo line. |
| `WASTE_DAMAGE` | **Keep** (any warehouse) | Dr per-line chosen expense account / Cr warehouse stock-in-hand, per line at FIFO rate. |
| `CORRECTION` | **Keep** (any warehouse) | Dr `default_stock_in_hand_account` / Cr warehouse stock-in-hand, per line — **zero net P&L effect** (asset-to-asset). For counting errors / data fixes. |
| `PHYSICAL_COUNT` | **Remove** | Redundant with CORRECTION — a physical count that finds a difference is itself a correction. A count that finds no difference posts nothing anyway. |

**Why remove PHYSICAL_COUNT:** a stocktake is the *discovery mechanism*; the resulting
difference is either a correction (no P&L) or a loss (wastage/damage). Keeping both
PHYSICAL_COUNT and CORRECTION forces an arbitrary choice with identical accounting. One
"Correction" reason covers it. This is recorded as an intentional scope decision.

> If the developer disagrees, PHYSICAL_COUNT can be kept as a fourth reason with the same
> accounting as CORRECTION (no P&L effect) — but it would be a pure label with no accounting
> distinction. Default proposal is to remove it.

---

## 4. Design

### 4.1 Per-line expense account

Each `StockReconciliationItem` gets an optional `expense_account` FK:

- Required for `WASTE_DAMAGE` lines with a negative difference (shortage).
- Hidden/ignored for `CONSUMPTION` (uses the configured wastage account) and `CORRECTION`
  (uses the stock-in-hand account).
- Queryset: enabled leaf P&L accounts (`is_group=False`).

> This matches the developer's earlier decision: "Per reason, per line (Recommended)" — the
> offset expense account is chosen per line, not a single fixed account.

### 4.2 Settings — one new Restaurant field

| Field | Type | Purpose |
|---|---|---|
| `wastage_account` (exists) | FK LedgerAccount | Offset for **CONSUMPTION** reconciliation lines. Already seeded to COGS. |
| `default_stock_in_hand_account` (exists) | FK LedgerAccount | Offset for **CORRECTION** lines (already used by supplier invoices). |
| **new** — none needed for reconciliation | — | WASTE_DAMAGE uses per-line accounts; CONSUMPTION uses existing `wastage_account`; CORRECTION uses existing stock-in-hand. |

No new Restaurant field is required. The two existing accounts fully cover the three reasons.

### 4.3 GL posting (new `post_stock_reconciliation_gl` in `apps/accounting/services.py`)

Posted at submit time, atomically with the SLEs. Voucher type `"Stock Reconciliation"`,
voucher_no `str(reconciliation.pk)`, posting_date = reconciliation posting date.

Per line with a non-zero difference, at the SLE's FIFO `outgoing_rate` (shortage) or
`incoming_rate` (surplus):

| Reason | Shortage (Dr / Cr) | Surplus (Dr / Cr) |
|---|---|---|
| CONSUMPTION | Dr `wastage_account` / Cr warehouse stock-in-hand | (blocked by validation — Kitchen can't gain stock) |
| WASTE_DAMAGE | Dr line `expense_account` / Cr warehouse stock-in-hand | Dr warehouse stock-in-hand / Cr line `expense_account` (rare; reversed as income) |
| CORRECTION | Dr `default_stock_in_hand_account` / Cr warehouse stock-in-hand | Dr warehouse stock-in-hand / Cr `default_stock_in_hand_account` |

The warehouse's stock-in-hand account is `Warehouse.account` (already the credited account
for settle-time drink deductions — consistent with existing behavior).

### 4.4 Idempotency & reversal

- `post_stock_reconciliation_gl` is idempotent: skip if a non-cancelled GL row already
  exists for this voucher.
- **Cancel** (`cancel_stock_reconciliation`) reverses via the existing `_reverse_gl`
  pattern (mirrored rows, originals flagged cancelled) — matching supplier invoice/payment.
- All inside the existing `submit_stock_reconciliation` `transaction.atomic()`.

### 4.5 Model changes

- `StockReconciliation.reason`: drop `PHYSICAL_COUNT` → choices `CONSUMPTION`,
  `WASTE_DAMAGE`, `CORRECTION`.
- `StockReconciliationItem.expense_account`: new nullable FK, PROTECT.
- `StockReconciliationItem.clean()`: for WASTE_DAMAGE lines, require an expense account
  when `qty < current_qty` (or when the computed difference is negative at submit, since
  `current_qty` is only filled at creation).

### 4.6 Submission validation

- CONSUMPTION: unchanged (Kitchen warehouse only, FOOD items only).
- WASTE_DAMAGE: requires per-line expense account for shortage lines.
- CORRECTION: no extra account requirements.
- OPENING_STOCK purpose: no GL posting (opening balances are set via the existing opening
  journal-entry flow); no reason required.

---

## 5. Implementation phases

### Phase A — Model + form changes

1. `apps/inventory/models.py`: remove PHYSICAL_COUNT from `reason` choices; add
   `expense_account` FK to `StockReconciliationItem`; add validation in `clean()`.
2. `apps/inventory/forms.py`: `StockReconciliationItemForm` gains `expense_account`
   (leaf P&L queryset, optional, hidden for non-WASTE_DAMAGE).
3. `apps/inventory/views.py` + templates: expose the new field in the reconciliation form;
   remove PHYSICAL_COUNT from any reason lists; reason filter still works.
4. Migration (schema) + data migration to relabel existing `PHYSICAL_COUNT` rows to
   `CORRECTION`.

### Phase B — GL posting

5. `apps/accounting/services.py`: add `post_stock_reconciliation_gl(reconciliation)`
   (per-line legs per §4.3, idempotent).
6. `apps/inventory/services.py::submit_stock_reconciliation`: call it inside the atomic
   block after SLE creation, before flipping SUBMITTED.
7. `cancel_stock_reconciliation`: call `_reverse_gl("Stock Reconciliation", str(pk))`.
8. `apps/accounting` helpers: ensure the warehouse account and wastage account resolve via
   `_resolve_required_account` (fail closed when unconfigured, like supplier invoice GL).

### Phase C — P&L integration (reports)

9. `apps/reports/sources.py::kitchen_consumption`: currently special-cases CONSUMPTION
   reconciliations. Keep as the source of the memo line, but make the memo read from the
   GL-consistent value (the SLE outgoing rates used at posting) so the memo equals the GL
   wastage debit. Document that this is a memo line (is_memo=True), not double-counted.

### Phase D — Tests & docs

10. Tests:
    - CONSUMPTION shortage → Dr wastage / Cr warehouse stock-in-hand at FIFO rate; cancel
      reverses.
    - WASTE_DAMAGE shortage → Dr per-line expense / Cr warehouse; cancel reverses; line
      without account fails validation.
    - CORRECTION → Dr stock-in-hand / Cr warehouse (no P&L effect); surplus variant.
    - Idempotency (double submit no-op).
    - P&L: kitchen-consumption memo equals GL wastage debit.
11. Docs: update `docs/workflows/inventory.md` mutation table, add reconciliation GL section
    to accounting docs, note the PHYSICAL_COUNT→CORRECTION decision in PLAN.md.

---

## 6. Risks & notes

- **FIFO rate availability**: a shortage's `outgoing_rate` is the FIFO cost — the same rate
  already used by `kitchen_consumption`. If a bin has zero-cost stock (e.g. opening stock at
  rate 0), the GL posts zero — acceptable, same as today's SLE behavior.
- **Surplus via WASTE_DAMAGE**: a count showing *more* stock than expected under
  WASTE_DAMAGE credits the expense account (income). Rare; validation could restrict
  WASTE_DAMAGE to negative differences only — flagged for developer decision.
- **Warehouse.account** must be set for every warehouse that can be reconciled, else the
  posting fails closed (consistent with existing drink-deduction behavior).
- **Consumption memo vs GL**: the Daily P&L memo line must not double-count; it is
  `is_memo=True` and sourced from the same reconciliation SLEs.
- **PHYSICAL_COUNT removal** is a product decision; the data migration relabels history.

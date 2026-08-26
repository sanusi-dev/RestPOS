# Implementation Plan: Migrate Restaurant Inventory from FIFO to Perpetual Weighted-Average Cost (PWAC)

## 1. Objective

Replace the current FIFO inventory valuation model with **Perpetual Weighted-Average Cost (PWAC)**.


The core principle is:

> **The StockBin represents the current inventory state. SLEs record the history of how that state changed. PWAC determines the cost of each transaction using the current WAC at the moment the transaction is processed.**

The voucher's `posting_date`/business date remains available for audit and reporting, but it does not determine the costing sequence.

This eliminates:

* FIFO
* historical queue snapshots on SLEs

---

# 2. Target Inventory Model

For every:

```text
Item + Warehouse
```

maintain one current `StockBin`.

```text
StockBin
─────────────────────────────
item_id
warehouse_id
quantity
stock_value
wac
etc....
```

The invariant is:

```text
wac = stock_value / quantity
```

when `quantity > 0`.

If quantity is zero:

```text
stock_value = 0
wac = 0
```

Negative stock is not permitted.

The SLE remains a historical record:

```text
StockLedgerEntry
────────────────────────────────
id
item_id
warehouse_id
voucher_type
voucher_id
movement_type
posting_datetime
quantity
unit_rate
stock_value_change
variance_amount
is_cancelled
```


---

# 3. Date Semantics

Store two separate concepts:

```text
posting_date
```

The date the transaction claims to have happened.

```text
created_at
```

The actual time the transaction entered the inventory system.



---

# 4. PWAC Formula

For a normal inbound transaction:

```text
old_value = stock_value
old_qty   = quantity

inbound_value = received_qty × actual_unit_cost

new_value = old_value + inbound_value
new_qty   = old_qty + received_qty

new_wac = new_value / new_qty
```

Example:

```text
Existing:
5 units
₦500 value
WAC = ₦100

Normal receipt:
2 units @ ₦150

Receipt value = ₦300

New quantity = 7
New value    = ₦800

New WAC = ₦800 / 7
        = ₦114.2857
```

For an outbound movement:

```text
cost = quantity × current_wac
```

Then:

```text
new_value = old_value - cost
new_qty   = old_qty - quantity

WAC remains unchanged
```

because:

```text
(old_value - qty×wac) / (old_qty - qty)
= wac
```

---

# 5. Normal Receipt

A normal receipt uses the actual receipt cost.

Flow:

```text
Receipt
  ↓
Lock StockBin
  ↓
Read current qty/value/WAC
  ↓
Calculate receipt value
  ↓
Increase qty
  ↓
Increase stock value
  ↓
Recalculate WAC
  ↓
Create SLE
  ↓
Commit
```

Example:

```text
Before:
10 units
₦1,000
WAC = ₦100

Receipt:
5 @ ₦140

After:
15 units
₦1,700
WAC = ₦113.33
```

---

# 6. Backdated Receipt / Backdated Addition

This is deliberately different from a normal receipt.

A backdated receipt means:

```text
posting_date < recorded date
```

but it is still processed against the current StockBin.

Do not replay anything.

Do not change historical sales.

Do not recalculate historical transfers.

Instead, value the late addition at the **current WAC**, and send the difference between the actual transaction cost and the current-WAC valuation to an Inventory Cost/Price Variance account.

Example:

```text
Current:

5 units
Stock value = ₦500
WAC = ₦100

Late receipt:

2 units @ ₦150
```

Inventory valuation:

```text
2 × current WAC ₦100
= ₦200
```

Actual document value:

```text
2 × ₦150
= ₦300
```

Variance:

```text
₦300 - ₦200
= ₦100
```

Result:

```text
StockBin:

quantity     = 7
stock_value  = ₦700
WAC          = ₦100
```

And:

```text
Inventory Cost Variance = ₦100
```

The key invariant is:

```text
inventory value increase
+
variance
=
actual transaction value
```

So:

```text
₦200 + ₦100 = ₦300
```

If the actual receipt cost is lower than current WAC, the variance is negative and must be posted with the corresponding accounting direction.

---

# 8. Normal Sale / Consumption

All outbound consumption uses current WAC.

```text
Sale
  ↓
Lock StockBin
  ↓
Check quantity >= requested quantity
  ↓
cost = qty × current WAC
  ↓
reduce quantity
  ↓
reduce stock value
  ↓
WAC remains unchanged
  ↓
create SLE
```

Example:

```text
Bin:
20 units
₦2,400
WAC = ₦120

Sale:
5

COGS = ₦600

Bin:
15 units
₦1,800
WAC = ₦120
```

No layer lookup is required.

---

# 9. Negative Stock

Negative stock is prohibited.

Every outbound transaction must perform:

```text
requested_qty <= stock_bin.quantity
```

before modifying the bin.

If false:

```text
raise InsufficientStock
rollback transaction
create no SLE
```

This applies to:

* sales
* waste
* stock issues
* external cancellations
* transfer-out
* transfer cancellation on the receiving warehouse

---

# 10. External Purchase Receipt Cancellation

Cancellation of an external receipt is a **new current-effective outbound adjustment**.

Suppose:

```text
Original receipt:
10 units @ ₦100
Original document value = ₦1,000

Current WAC = ₦120
```

Cancellation:

```text
Inventory value removed:
10 × ₦120
= ₦1,200
```

But the original transaction being reversed is worth:

```text
₦1,000
```

Therefore:

```text
Cancellation variance
= current inventory reversal
  - original document value

= ₦1,200 - ₦1,000
= ₦200
```

Accounting should post the ₦200 to the configured **Inventory Cost/Price Variance** account in the appropriate direction.

StockBin:

```text
quantity -= 10
stock_value -= 1,200
```

If quantity is less than 10:

```text
reject cancellation
```

No partial cancellation should occur unless the business explicitly supports partial cancellation as a separate operation.

---

# 11. External Sale Cancellation / Return

The same principle applies to an already-posted external outbound transaction.

Suppose:

```text
Original sale:
10 units
WAC at sale = ₦120

Original COGS = ₦1,200
```

Today:

```text
Current WAC = ₦150
```

Cancellation/return adds:

```text
10 × ₦150 = ₦1,500
```

to inventory.

The difference from the original COGS:

```text
₦1,500 - ₦1,200
= ₦300
```

is an inventory-cost/reversal variance according to the configured accounting treatment.

---

# 12. Internal Transfer

Transfer is a value movement between two StockBins.

Suppose:

```text
A:
100 units
₦15,000
WAC = ₦150
```

Transfer:

```text
10 units A → B
```

Source valuation:

```text
10 × ₦150 = ₦1,500
```

Warehouse A:

```text
quantity     -= 10
stock_value  -= ₦1,500
```

Warehouse B:

```text
quantity     += 10
stock_value  += ₦1,500
```

Then B recalculates its WAC.

There is no company-level gain/loss because value is simply moved:

```text
A -₦1,500
B +₦1,500
Net = ₦0
```

---

# 13. Transfer Cancellation

Cancellation is performed using the **current WAC of the destination warehouse**, because under PWAC we do not recover the historical transfer layer.

Original:

```text
A → B
10 units
```

Today:

```text
B WAC = ₦180
```

Cancellation:

```text
10 × ₦180 = ₦1,800
```

Warehouse B:

```text
-10 units
-₦1,800
```

Warehouse A:

```text
+10 units
+₦1,800
```

A recalculates its WAC.

No company-level variance is posted because this is an internal transfer:

```text
A +₦1,800
B -₦1,800
Net = ₦0
```

The original transfer value is retained in the audit trail, but it does not determine the cancellation valuation.

---

# 14. Stock Reconciliation

A reconciliation should be treated as a **current-state adjustment**

Example:

```text
Current:
quantity = 20
stock value = ₦2,000
WAC = ₦100

Physical count = 25
```

Adjustment:

```text
+5 units
```

The accounting treatment should explicitly define the valuation rate used for the adjustment.

Rule:

* Use the current WAC for the cost.

there are three type of reconcillation, wastage, adjustment, and consumption
consumption: it is the kitchen consuming kitchen stock (strictly kitchen stock)
wastage: there a warehouse dedicated for tracking waste, in reality wastes are disposed but we need a way to digitally track it so there is a warejouse where wastage is posted, so i dont know if updating the wastage warehouse be through transfer, or just record a wastage reconcillation and no warehouse, so we track wastage through sle records. i need to research the best pratice for that.
adjyusment: this is for correction, when physical couting is done

---

# 15. SLE Design

SLEs should be treated as an **append-only audit/event history**.

They should record:

```text
item
warehouse
voucher
movement_type
posting_date
quantity
unit_rate
stock_value_change
variance_amount

```


---

# 16. StockBin Is the Current Truth

`StockBin` should contain:

```text
quantity
stock_value
wac
```

and be treated as the current operational state.


# 22. Business Rules to Lock Down Before Implementation

The following rules should be explicit and tested:

| Event                              | Business date allowed to be old? | Costing behavior                  |
| ---------------------------------- | -------------------------------: | --------------------------------- |
| Normal receipt                     |                              Yes | Normal WAC receipt                |
| Backdated receipt                  |                              Yes | Normal WAC receipt (full blend)   |
| Sale                               |                        Prefer no | Current WAC                       |
| Waste/consumption                  |                        Prefer no | Current WAC                       |
| Transfer                           |                   Prefer current | Source current WAC                |
| Transfer cancellation              |      Yes, references old voucher | Current destination WAC           |
| External receipt cancellation      |                              Yes | Current WAC + external variance*  |
| Sale cancellation/return           |                              Yes | Current WAC + applicable variance |
| Reconciliation                     |                   Prefer current | Current-state adjustment          |
| Future-dated inventory transaction |                           Reject | Avoid scheduled-cost ambiguity    |

\* With GRN (see §23), external receipt cancellation is **blocked** if a submitted Supplier Invoice references the receipt (ERPNext `check_next_docstatus` behaviour) — cancel the invoice first.

The conceptual rule is:

> **Every inventory transaction is a state transition against the current StockBin. PWAC determines the inventory carrying cost at that moment. The SLE records what happened. Business/posting dates explain the transaction historically but do not cause historical inventory valuation to be reconstructed.**

That is the core design to implement and test.

---

# 23. Solidified Decisions (2026-05-11) — Overrides to §§6, 14, 22

These were locked via interactive questions and industry research (ERPNext Purchase Receipt `gl_composer.py` / `purchase_receipt.py:437-450`). They override the draft text above where they conflict.

### D1 — Backdated receipts: full WAC blend, no variance (overrides §6, §22)

*Decided:* **Full WAC blend at actual cost (QuickBooks-style).** A receipt with `posting_date < created_at` is costed identically to a normal receipt:

```text
inbound_value = received_qty × actual_unit_cost
new_value = old_value + inbound_value
new_qty   = old_qty + received_qty
new_wac   = new_value / new_qty
```

*Rejected alternative:* Dynamics 365-style "value at current WAC + variance to price-variance account" (the draft §6). Reason: it adds GL complexity for a single-location restaurant where late paperwork is common; blending preserves `wac = stock_value / quantity` and is industry-standard for perpetual WAC.

All backdated receipts blend. No `variance_amount` on receipt SLEs.

### D2 — Wastage: no new warehouse, reuse existing account (clarifies §14)

*Decided:* No `wastage_warehouse` on `Restaurant`. Keep `WASTE_DAMAGE`/`wastage` as a `StockReconciliation.reason` on the real warehouse, valued at current WAC, posted to the **existing** `Restaurant.wastage_account`. No new settings field. Matches ERPNext practice (Material Issue purpose, not a warehouse).

*Decided:* `CONSUMPTION` remains strictly kitchen stock (FOOD production warehouse) — unchanged.

### D3 — Opening stock: entered rate seeds WAC

*Decided:* `OPENING_STOCK` reconciliation lines post at the user-entered `valuation_rate`, establishing the initial `wac`. All subsequent receipts blend. `RECONCILIATION` adjustments use current WAC.

### D4 — GRN at receipt (accrual, ERPNext-style)

*Decided:* **Receipt posts GL.** On Purchase Receipt submit (provisional):

```text
Dr Stock-in-hand (warehouse asset account)   qty × rate
Cr GRNI — Stock Received But Not Billed      qty × rate
```

New `Restaurant.stock_received_but_not_billed_account` (GRNI) + seed in chart of accounts.

Supplier Invoice posting changes (see §4.1 Phase 2 override):
- If `purchase_receipt` linked and stock line: **Dr GRNI / Cr Payable** (clears GRNI). If invoice net rate ≠ receipt rate, difference → **Dr/Cr Inventory Price Variance** (new account, D5) via `amount_difference` entry (ERPNext `make_amount_difference_entry`).
- If no linked receipt (direct invoice): **Dr Stock-in-hand / Cr Payable** (current behaviour, retained for non-receipt invoices).
- Expense lines: unchanged (Dr Expense / Cr Payable).

This mirrors ERPNext `PurchaseReceiptGLComposer.make_stock_received_but_not_billed_entry` + `make_item_asset_inward_gl_entry`.

### D5 — New dedicated variance account

*Decided:* New `Restaurant.inventory_price_variance_account` (seeded), separate from `wastage_account`. Used for: receipt↔invoice rate differences and external cancellation/return variances (§§10-11). Not reused for wastage.

### D6 — Receipt cancellation guard (ERPNext `check_next_docstatus`)

*Decided:* Cancelling a Purchase Receipt is **blocked** if a submitted `SupplierInvoice` references it (`purchase_receipt_id` + `status=SUBMITTED`). Caller must cancel the invoice first (which posts reversal of GRNI/Payable). This removes the §10 variance-on-blocked-path complexity and matches ERPNext `on_cancel: check_next_docstatus`. Un-invoiced receipts cancel normally (reverse GRNI/SLE at current WAC, no variance).

### D7 — Data migration: clean slate

*Decided:* No production stock data to preserve. Migration will clear existing `StockLedgerEntry`, `Bin` (`StockBin`) FIFO queue snapshots via `RunPython` (dev-data wipe), not a FIFO→WAC replay. Inventory documents remain; Bins rebuild on next submit via WAC. No customer impact.

### D8 — Date thresholds

*Decided:* "Backdated" = any `posting_date < created_at::date`. No separate pre-last-SLE threshold. All such receipts blend as D1.

---

*Prompt.md is now the solidified plan. Next step: transcribe the decision-only plan into `PLAN.md §4` and implement per AGENTS.md protocol.*

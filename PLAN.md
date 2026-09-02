# RestPOS — Implementation Plan

This document is the implementation roadmap. Section 3 tracks the build sequence; Section 4
holds decision-only detailed plans for the unbuilt phases. Product facts live in `FEATURES.md`
and `docs/`; working conventions live in `AGENTS.md`.

## 1. Project Overview

RestPOS is a restaurant POS and management system for a single Nigerian restaurant location:
cashier-operated ordering, kitchen/bar ticket printing, payments, shifts, inventory, and a
food-vs-drinks departmental split. It runs entirely on the local network with no internet
dependency. The full product specification is in `FEATURES.md`; the tech stack and coding
conventions are in `AGENTS.md`.

## 2. Application Architecture

| App | Responsibility | FEATURES.md sections | State |
|---|---|---|---|
| `settings` | Restaurant singleton, production units, staff roles | A1 | built |
| `inventory` | Item master, groups, warehouses, stock ledger, stock entries, reconciliations, purchase receipts, stock reports | A3 | built |
| `menu` | Menu definition, menu items, variants, add-ons | A2 | built |
| `payments` | Payment modes, GL mappings | A4 | built |
| `staff` | POS opening/closing entries, shift reconciliation | A5 | built |
| `orders` | Orders, order items, payments, KOT/BOT tickets, returns, audit events, POS workbench | A6, A7, B | built |
| `accounting` | Chart of accounts, GL entries, journal entries, fiscal years, supplier payables | A8, A9 | built |
| `reports` | Daily P&L, sales reports, trial balance | A10, E #63 | built (Daily P&L); sales reports planned |
| `printing` | Print agent client, ESC/POS formats, printer routing | E #64 | planned |
| `customers` | Customer master, groups, credit limits | F #65 | deferred |
| `coupons` | Coupon codes, pricing rules, cashier discount | F #66 | deferred |

**Build order:** `settings` first (every app references the `Restaurant`); `inventory` before
`menu` (menu items link the Item master); `payments` and `staff` are standalone and precede
`orders` (orders stamp the active shift and reference payment modes); `orders` is the central
app built on all of the above; `accounting` then layers GL posting on orders, payments,
inventory, and settings; `reports` consumes everything; `printing` is a leaf built last.
Deferred apps (customers, coupons) are picked up only after the core phases complete. Each
phase completes before the next starts.

## 3. Build Sequence

| Phase | Apps involved | Features covered | Completed work | Remaining work | Detailed plan status | Progress status |
|---|---|---|---|---|---|---|
| 1 | settings | A1 | Restaurant singleton (company, invoice prefix, warehouses, draft cap, history toggle), production units with printer config, staff role assignment | — | n/a | Completed |
| 2 | inventory | A3, A9 | Item master with independent flags, groups, warehouses, immutable PWAC stock ledger, receipts/transfers/reconciliations, purchase receipts (GRNI accrual), bins, stock reports, supplier payables (supplier master, receipt-first invoices, payments, allocations) | — | n/a | Completed |
| 3 | menu | A2 | Menu, menu items, specials, disable, images, variants, add-ons, seed command | — | n/a | Completed |
| 4 | staff, payments | A4, A5 | Payment modes with default + GL mappings, opening/closing entries, reconciliation, refund netting | — | n/a | Completed |
| 5 | orders | A6, A7, B, C | POS workbench, order lifecycle with stage exits and returns, KOT/BOT tickets with print status, group ordering, audit events, orders control room | — | n/a | Completed |
| 6 | accounting | A8 | GL core + order posting, refunds completion, opening balances, cash variance posting | — | n/a | Completed |
| 7 | reports | A10 | Daily P&L document with amendments and departmental split | — | n/a | Completed |
| 8 | reports | E #63 | — | Sales reports, trial balance, simple P&L | §4.7 | Planned |
| 9 | printing | E #64 | Print stub (always succeeds); printer config lives on production units | Print agent, ESC/POS receipt + ticket formats, routing and status | §4.8 | Planned |
| — | customers | F #65 | Free-text customer name on orders | Customer master, groups, credit limits, POS search/create | deferred by design | Deferred |
| — | coupons | F #66 | — | Coupon codes, pricing rules, cashier discount | deferred by design | Deferred |

Progress statuses: `Completed` (implemented, tested, lint clean), `Under implementation`,
`Planned` (detailed plan written, ready to implement), or `Deferred` (intentionally out of
scope until further notice). "n/a" in the detailed-plan column means the phase is complete and
its plan is retired.

## 4. Detailed Implementation Plans

Plans for unbuilt work only. Each plan holds the finalized implementation decisions and
nothing else. Completed-phase plans are retired; current product facts are in `FEATURES.md`,
`docs/`, and the code itself.

### 4.1 Supplier Payables and Supplier Invoices (Phase 2)

**Status:** complete — implemented and retired (including the PWAC GRNI rework and the
receipt-first invoice UX); current product facts are in `FEATURES.md`, `docs/`, and the code.

**Decisions:**

- A `Supplier` master separate from the `supplier_name` string on `PurchaseReceipt`; the
  receipt keeps its free-text field for quick entry and optionally links to a Supplier.
- No purchase orders. The `PurchaseReceipt` is the goods-received record; the payable
  source document is the `SupplierInvoice`.
- **Receipt-first invoices.** Stock lines are not user input. The draft form takes header
  fields plus optional expense lines. On `submit()`, `build_supplier_invoice_stock_lines`
  creates `SupplierInvoiceItem` rows from the linked receipt (qty/rate copied). Stock
  lines are read-only thereafter. Expense-only invoices need no receipt.
- Two line models: `SupplierInvoiceItem` (stock, service-created) and
  `SupplierInvoiceExpense` (description + amount, user-edited on the draft).
- **GRN at receipt (accrual).** Receipt: Dr SIH / Cr GRNI @ receipt rate. Linked invoice:
  Dr GRNI / Cr payable @ the same rate (qty/rate lock). No unlinked Dr SIH / Cr payable
  path. Market purchases use `StockEntry MATERIAL_RECEIPT` → Dr SIH / Cr expense (no GRNI,
  no invoice). See §4.9.
- Expense lines post Dr `Restaurant.default_supplier_expense_account` / Cr payable.
  Missing config is a hard error at submit.
- Accounts-payable balances live on `SupplierInvoice.outstanding_amount` (set to total on
  submit, reduced by payment allocations). `Supplier.outstanding_balance` sums those
  fields. `SupplierPayment` is fully allocated: `paid_amount` equals the sum of allocation
  rows.
- **One default payable account** (`Restaurant.default_payable_account`) with an optional
  per-supplier `payable_account` override.
- Cancel chain: Payment → Invoice → Receipt. A submitted invoice (or allocated payment)
  blocks receipt cancellation.

**Models:** Supplier, SupplierInvoice, SupplierInvoiceItem, SupplierInvoiceExpense,
SupplierPayment, SupplierPaymentAllocation.

##### Models

**Supplier**

| Field | Type | Notes |
|---|---|---|
| `supplier_name` | CharField(200) unique | the supplier's name is the key |
| `supplier_type` | choices Company/Individual, default Company | |
| `contact_person` / `phone` / `email` | CharField(100) blank | |
| `address` | TextField blank | |
| `tax_id` | CharField(50) blank | supplier's TIN |
| `payable_account` | FK LedgerAccount, PROTECT, null | per-supplier AP account override |
| `is_default` | Boolean, default False | sole supplier used by quick entry |
| `disabled` | Boolean, default False | blocked from new transactions; history retained |

Validation: a supplier's `payable_account`, when set, must be a leaf, enabled, and not
frozen (same rule as GL posting). `is_default` — saving a supplier with `is_default=True`
clears the flag on all others (same pattern as the default payment mode). Disabled
suppliers are excluded from transaction forms but keep their historical documents.

**SupplierInvoice**

| Field | Type | Notes |
|---|---|---|
| `invoice_number` | CharField(50) unique, editable=False | `{Restaurant.invoice_series_prefix}PINV-{pk}` |
| `supplier` | FK Supplier, PROTECT | |
| `posting_date` | DateField | default today; must fall in an enabled fiscal year |
| `due_date` | DateField | default = posting_date; `>= posting_date` |
| `bill_no` / `bill_date` | CharField(100) blank / DateField null | the supplier's own invoice reference |
| `purchase_receipt` | FK PurchaseReceipt, SET_NULL, null, blank | required at submit when stock lines exist; cannot change once set |
| `status` | DRAFT/SUBMITTED/CANCELLED | immutable workflow, like all financial documents |
| `total` | Decimal(14,2), editable=False | recomputed from stock + expense lines on submit |
| `outstanding_amount` | Decimal(14,2), editable=False | set to total on submit; reduced by payment allocations |
| `remarks` | TextField blank | |

`supplier_name` text on the receipt is preserved for quick entry and does not create a
`Supplier` automatically. An invoice's `purchase_receipt` cannot change once set (even
on a draft). Submit requires at least one stock line or expense line.

**SupplierInvoiceItem** (stock only — created from the receipt on submit)

| Field | Type | Notes |
|---|---|---|
| `invoice` | FK SupplierInvoice, CASCADE, related_name="items" | |
| `item` | FK Item, PROTECT, null=True | required; auto-filled from the receipt line |
| `source_receipt_line` | FK PurchaseReceiptItem, SET_NULL, null, blank | required when the invoice is receipt-linked; unique per receipt line |
| `description` | CharField(200) blank | defaults to the item name |
| `qty` | Decimal(10,2), default 1 | copied from `received_qty` |
| `rate` | Decimal(10,2) | copied from the receipt line; `>= 0` |
| `amount` | Decimal(14,2), editable=False | `qty * rate` |
| `received_qty` / `amount_per_unit` | Decimal(10,2) / Decimal(10,2), editable=False | snapshot from `source_receipt_line` |

Validation: enabled stock + purchase item, `qty > 0`, `rate >= 0`. A receipt-linked
invoice's stock lines must each point at a submitted receipt line whose supplier matches;
qty/rate must equal the receipt line (GRNI rate lock). Draft-only add/edit/delete.

**SupplierInvoiceExpense**

| Field | Type | Notes |
|---|---|---|
| `invoice` | FK SupplierInvoice, CASCADE, related_name="expenses" | |
| `description` | CharField(200) | required, non-blank |
| `amount` | Decimal(14,2) | `> 0` |

Draft-only add/edit/delete. The expense account is not per line — posting uses
`Restaurant.default_supplier_expense_account`.

**SupplierPayment**

| Field | Type | Notes |
|---|---|---|
| `payment_number` | CharField(50) unique, editable=False | `{prefix}PAY-{pk}` |
| `supplier` | FK Supplier, PROTECT | |
| `posting_date` | DateField | default today; must fall in an enabled fiscal year |
| `mode_of_payment` | FK ModeOfPayment, PROTECT | must be enabled and have a GL mapping |
| `paid_amount` | Decimal(14,2) | `> 0`; total of allocation rows, allocated at submit |
| `reference_no` / `reference_date` | CharField(50) blank / DateField null | cheque/bank reference |
| `status` | DRAFT/SUBMITTED/CANCELLED | |
| `remarks` | TextField blank | |

A payment is fully allocated: `paid_amount` equals the sum of its allocation rows (the
draft form adds rows from outstanding invoices and validates the totals match on submit —
excess over outstanding is rejected, mirroring ERPNext's `difference_amount` check).
Defaults: the CASH `ModeOfPayment` GL mapping for cash payments; BANK modes require a
non-blank `reference_no`.

**SupplierPaymentAllocation**

| Field | Type | Notes |
|---|---|---|
| `payment` | FK SupplierPayment, CASCADE, related_name="allocations" | |
| `invoice` | FK SupplierInvoice, PROTECT, related_name="allocations" | |
| `outstanding_amount` | Decimal(14,2), editable=False | snapshot at creation |
| `allocated_amount` | Decimal(14,2) | `> 0`, `<= outstanding_amount` at submit |

The allocation row records how much of this payment applies to one invoice. Submit
reduces that invoice's `outstanding_amount`; cancel restores it. The payment GL is a
single Dr payable / Cr cash-bank pair for `paid_amount`, not per-allocation rows.

##### Posting rules

`accounting.services.post_supplier_invoice_gl(invoice)` runs inside the invoice's
`submit()` atomic block; `post_supplier_payment_gl(payment)` inside the payment's.
Both use the existing `GLEntry.post` (resolves the fiscal year from `posting_date`,
fails closed when the payable chain is missing), and both are idempotent — a second
submit returns without re-posting.

**Supplier invoice** — `voucher_type="Supplier Invoice"`, `voucher_no=invoice_number`,
resolved fiscal year. `submit()` calls `build_supplier_invoice_stock_lines` first, then
validates stock + expense lines, then posts.

| Leg | Dr | Cr | Amount | Account resolution |
|---|---|---|---|---|
| GRNI | stock lines | — | Σ stock-line amounts | `Restaurant.stock_received_but_not_billed_account` (required). Stock invoices must link a purchase receipt; qty/rate must match the receipt line. |
| Expense | expense lines | — | Σ expense amounts | `Restaurant.default_supplier_expense_account` (required when any expense line exists) |
| Accounts Payable | — | payable | grand total | `supplier.payable_account` → `Restaurant.default_payable_account` (required) |

`against` on every leg is the payable account name. Cancellation posts mirrored negated
rows with the originals marked `is_cancelled`. **No stock-ledger entries are posted by
the invoice** — stock moves only on the receipt. Cancelling a submitted invoice is
refused while submitted payment allocations exist — cancel those payments first, then
the invoice.

**Supplier payment** — `voucher_type="Supplier Payment"`, `voucher_no=payment_number`,
resolved fiscal year:

| Leg | Dr | Cr | Amount | Account resolution |
|---|---|---|---|---|
| Accounts Payable | payable | — | total allocated | `supplier.payable_account` → `Restaurant.default_payable_account` (required) |
| Cash / Bank | — | mode account | total allocated | `ModeOfPayment` GL mapping (required) |

`against` on the AP side = the payment mode account name; on the cash side = the payable
account name. Cancellation reverses the posted rows and restores each invoice's
`outstanding_amount`.

**Outstanding maintenance:** submitting an invoice sets `outstanding_amount = total`.
Submitting a payment subtracts each allocation from the invoice; cancelling a payment
adds it back. A cancelled invoice zeros outstanding. `Supplier.outstanding_balance` sums
submitted invoices' `outstanding_amount`. Payment status is derived: `Paid` when
outstanding is 0, `Partly Paid` when 0 < outstanding < total, else `Unpaid`.

##### Changes outside a new app

- `settings.Restaurant` gains `default_payable_account`,
  `default_supplier_expense_account`, `default_stock_in_hand_account`,
  `stock_received_but_not_billed_account` (GRNI), and
  `inventory_price_variance_account` (cancellation WAC drift — see §4.9). The settings
  form has a Payables section.
- `apps/payments` is untouched — `ModeOfPayment` GL mappings already exist.
- `PurchaseReceipt` keeps its free-text `supplier_name` plus optional `supplier` FK.
  Submit posts Dr SIH / Cr GRNI; cancel is blocked while a submitted invoice exists.
- No new apps. Payables live in `apps/accounting` (`payables_models.py`,
  `payables_views.py`, `payables_forms.py`; templates under
  `templates/backoffice/accounting/payables/`).
- Nav: **Payables** group (Suppliers, Supplier Invoices, Supplier Payments) under
  Accounting.

##### Frontend

All pages extend the backoffice base; Manager/Admin only (same gate as accounting):

- **Suppliers** — register list with outstanding balance column and a New Supplier
  page; detail page shows documents (invoices, payments) and the balance; create/edit
  form with `is_default` + `payable_account` fields.
- **Supplier Invoices** — register (filters: status, supplier); create/edit form with
  header fields, a read-only purchase-receipt preview (after the draft is saved with a
  receipt linked), and an HTMX expense-line formset. Submit generates stock lines from
  the receipt. Detail shows receipt stock lines, expense lines, and GL drill-down.
- **Supplier Payments** — create form with outstanding-invoice picker (rows auto-filled
  from outstanding), allocated total vs paid amount validation; detail page shows the
  allocations and linked GL.
- **Dashboard cards** — the accounting dashboard gains "Payables" cards (total
  outstanding, count of unpaid invoices) linking to the registers.

##### Seeds

`seed_chart_of_accounts` extends to create (idempotent) `Accounts Payable`,
`Stock Received But Not Billed` (GRNI), `Stock in Hand`, `Supplier Expenses`, and
`Inventory Price Variance`, wiring the matching Restaurant FKs when they are null.

##### Activation and rollout

- No payable off-switch. Invoice/payment submit fail closed when the payable, GRNI, or
  (when expense lines exist) default supplier-expense account is missing. Purchase
  receipt submit fails closed without GRNI and the Store warehouse account.
- Existing unpaid supplier balances import as opening payables (see §4.4 opening
  JournalEntry) — the ledger does not reconstruct historical receipts.
- Go-live sequence: run `seed_chart_of_accounts` (creates the payable accounts and
  wires the Restaurant FKs) → configure any per-supplier `payable_account` overrides →
  the data migration creates `Supplier` rows from existing receipt text during
  `migrate`.

##### Tests

- `apps/accounting/tests/test_payables.py` — supplier validations; receipt-first stock
  line generation; GRNI/payable/expense posting legs; rate lock; missing
  supplier-expense account fails closed; payment allocation and outstanding; cancel
  reversals and idempotence.
- `apps/inventory/tests/test_purchase_receipt.py` — optional `supplier` link; GRNI
  posting; cancel blocked while a submitted invoice exists.

### 4.2 Accounting / GL (Phase 6)

**Status:** complete — implemented and retired; current product facts are in `FEATURES.md`, `docs/`, and the code.

**Scope decisions (locked):**

1. Single-tier posting: the Order is the accounting document. GL posts at order settle and
   reverses at order cancel. No consolidated sales invoices at shift close; the close keeps
   consuming aggregates only.
2. No party/receivable ledger. All sales are walk-in cash/bank.
3. No tax GL. There is no tax system.
4. COGS at settle from the current WAC (`unit_rate`) of the settle-time drink stock deductions.
5. Inventory documents post GL (see §4.9): purchase receipts Dr SIH / Cr GRNI; stock-entry
   market receipts Dr SIH / Cr expense; transfers are intra-inventory (no GL); waste
   reconciliations Dr wastage / Cr warehouse.
6. Return orders post no GL in the GL core; refund GL posts in refunds completion (§4.3),
   within the same phase.
7. Amendment chain (`amended_from`) applies to JournalEntry only. Write-off vouchers are
   not used — wastage (returns marked not-restockable, WASTE_DAMAGE reconciliations) and
   cash variance cover the restaurant's loss cases.

**New app:** `apps/accounting`, URL namespace `accounting` under `backoffice/accounting/`,
behind the backoffice role gate.

##### Models

**LedgerAccount**

| Field | Type | Notes |
|---|---|---|
| `name` | CharField(200) unique | account name is the key |
| `parent` | FK self, PROTECT, null=True | null = root |
| `is_group` | Boolean, default False | |
| `root_type` | choices ASSET/LIABILITY/EQUITY/INCOME/EXPENSE, blank | required on roots, inherited below |
| `report_type` | choices BALANCE_SHEET/PROFIT_AND_LOSS, blank | inherited below |
| `account_type` | choices (Cash, Bank, Stock, Income Account, Expense Account, Cost of Goods Sold, Round Off, Equity, …) | restaurant-relevant subset |
| `account_number` | CharField(50) blank | optional |
| `freeze_account` | Boolean, default False | blocks new GL entries while set |
| `disabled` | Boolean, default False | |

Tree is a flat FK parent, not Nested Set. Validation: parent must be a group; no self-parent
or cycles; roots require `root_type`; a group with children cannot be disabled; a leaf cannot
gain children. Deletion PROTECTed against GL, journal rows, payment mappings, and configured
account FKs.

**FiscalYear**

| Field | Type |
|---|---|
| `name` | CharField(10) unique |
| `year_start_date` / `year_end_date` | DateField |
| `disabled` | Boolean, default False |
| `is_short_year` | Boolean, default False |

Validation: end after start; enabled years cannot overlap. `get_for(date)` returns the enabled
year covering a date or raises.

**GLEntry**

| Field | Type | Notes |
|---|---|---|
| `posting_date` | DateField | |
| `account` | FK LedgerAccount, PROTECT | leaf accounts only |
| `debit` / `credit` | Decimal(14,2), default 0 | exactly one non-zero |
| `against` | CharField(200) | comma-joined balancing account names |
| `voucher_type` / `voucher_no` | CharField(50/100) | e.g. "Order" + invoice number |
| `remarks` | TextField blank | |
| `fiscal_year` | FK FiscalYear, PROTECT | resolved from posting_date |
| `is_cancelled` | Boolean, default False | flipped by reversals, never un-flipped |
| `is_opening` | Boolean, default False | |

Immutability: `save()` blocks edits on existing rows except the reversal flag; `delete()`
raises. Posting validation: leaf, enabled, not frozen account; posting_date within the
resolved fiscal year.

**JournalEntry**

| Field | Type | Notes |
|---|---|---|
| `voucher_type` | choices JOURNAL/CASH/BANK/OPENING, default JOURNAL | |
| `posting_date` | DateField | |
| `reference_no` / `reference_date` | CharField(50) / DateField null | |
| `remark` | TextField blank | |
| `status` | DRAFT/SUBMITTED/CANCELLED | |
| `total_debit` / `total_credit` | Decimal(14,2), editable=False | recomputed on save |
| `difference` | Decimal(14,2), editable=False | must be 0 to submit |
| `is_opening` | Boolean, default False | |
| `amended_from` | FK self, SET_NULL, null=True | amendment chain |

Methods: `submit()` (atomic; rows may not mix debit and credit, no duplicate
account rows, difference 0, total > 0; posts one GLEntry per row; a
`voucher_type=OPENING` entry sets `is_opening=True` automatically), `cancel()` (atomic;
mirrored negated entries, originals marked `is_cancelled`), `amend()` (only from CANCELLED;
copies into a new DRAFT linked via `amended_from`; rejected if an amendment already exists,
so a cancelled entry has at most one amendment).

**JournalEntryAccount**

| Field | Type |
|---|---|
| `journal_entry` | FK JournalEntry, CASCADE |
| `account` | FK LedgerAccount, PROTECT |
| `debit` / `credit` | Decimal(14,2), default 0 |
| `remarks` | CharField(200) blank |

##### Changes outside accounting

- `payments.PaymentGLMapping.default_account`: CharField → FK LedgerAccount, PROTECT;
  leaf-only validation. Data migration matches existing strings by name (case-insensitive),
  creating a missing leaf account under Assets (Cash/Bank by mode type).
- `settings.Restaurant` gains nullable FKs: `default_income_account`,
  `default_expense_account`, `round_off_account`, `account_for_change_amount`,
  `wastage_account` (consumed by §4.3), `cash_shortage_account`,
  `cash_over_short_account`, `variance_approval_threshold` (Decimal, consumed by §4.5).
  Settlement enforces the ones it needs; the settings form gains an Accounting section.
- `settings.ProductionUnit.income_account`: FK LedgerAccount, null — the departmental split
  hook (Kitchen = FOOD income, Bar = DRINKS income).
- `inventory.ItemGroup` gains `income_account` / `expense_account` FKs.
- `inventory.Warehouse.account`: FK LedgerAccount, null — credited with the stock value of
  settle-time drink deductions.
- `apps/orders/management/commands/seed_pos_setup.py` seeds accounts before creating
  `PaymentGLMapping` rows.

##### Posting rules — order settle

`accounting.services.post_order_gl(order)` runs inside `settle_order`'s atomic block after the
order flips SUBMITTED and the drink deductions are written. All entries carry
`voucher_type="Order"`, `voucher_no=invoice_number`, `posting_date`, and resolved fiscal year.

| Leg | Dr | Cr | Amount | Account resolution |
|---|---|---|---|---|
| Income | — | income account | Σ item amounts per account | `ItemGroup.income_account` → `ProductionUnit.income_account` (by line department) → `Restaurant.default_income_account` (required — settle raises if empty) |
| Payment | payment account | — | per OrderPayment `amount`, reduced by change on the row whose account equals `Restaurant.account_for_change_amount` | `ModeOfPayment` GL mapping (required) |
| Round-off | — | `Restaurant.round_off_account` | `rounding_adjustment` (may be negative) | required when non-zero |
| COGS | expense account | `order.stock_warehouse.account` | current WAC (`unit_rate`) of the settle-time drink deductions, per account | `ItemGroup.expense_account` → `Restaurant.default_expense_account` (required when stock items exist) |

`against` holds the balancing account names; entries sharing account/against merge.
Order cancel posts mirrored negated entries, originals `is_cancelled=True`.

##### Frontend

All pages extend the backoffice base; the nav gains an Accounting section (Chart of Accounts,
Journal Entries, GL Entries, Fiscal Years). Chart of accounts is a tree page with
HTMX expand/collapse; journal entries use the existing formset add/remove row pattern with
submit/cancel/amend POST buttons; GL entries are a read-only filtered table; fiscal years
are simple CRUD pages.

##### Seeds

`seed_chart_of_accounts` (idempotent): Assets → Cash Account, Bank Accounts → Electronic
Account; Inventory stock leaves per warehouse; Income → Food Sales + Drinks Sales; Expenses →
Cost of Goods Sold + Round Off; Equity → Owner's Equity. Creates the current-year fiscal year,
and fills production-unit income accounts, warehouse accounts, Restaurant defaults, and
payment GL mappings only when those FKs are currently null.

##### Activation and rollout

- There is no accounting off-switch. Once the phase ships, order settlement posts GL —
  settlement fails closed when the required account chain is missing (no silent
  gap between sales and the books).
- Go-live sequence: run `seed_chart_of_accounts` (idempotent) → run `seed_pos_setup`
  (which now invokes the chart seed first) → configure the Restaurant accounting FKs in
  settings → the data migration in `payments` converts existing `PaymentGLMapping` strings
  to FK values during `migrate`. Checkout works only after this sequence completes.

##### Tests

- `test_models.py` — account tree rules, fiscal year rules + `get_for`, GL immutability.
- `test_journal_entry.py` — balanced submit, unbalanced/mixed-row/duplicate rejections,
  frozen/disabled/group account rejections, cancel reversal, amend chain.
- `test_order_gl.py` — settle legs incl. departmental income split, change reduction,
  rounding, COGS; cancel reversal; missing account config raises; fiscal year guard raises.
  (Return-order GL is covered by §4.3 tests.)
- `test_payment_gl_mapping.py` — FK + leaf-only validation.
- `test_views.py` — backoffice gate and CRUD flows.
- Existing orders/staff suites gain a shared accounting setup helper because settlement now
  requires the account chain.

### 4.3 Refunds Completion (Phase 6)

**Status:** complete — implemented and retired.

**Decisions:**

- **Refund GL on return submit.** `submit_return` posts refund GL inside its own atomic block
  after the return flips SUBMITTED. Legs are rebuilt from the returned lines (income per
  returned amount, payment credits from the return's `OrderPayment` rows, drink COGS reversed
  at the restore's current WAC), carrying the return's invoice number as
  `voucher_type="Order"`. The batch is plugged to the round-off account so it cannot drift.
  Restockable drink lines restore the bin via a "POS Return" SLE at current WAC; the SLE
  records `SALE_RETURN` variance vs the original sale WAC (net COGS effect of refunding at
  current WAC). Refund payments are proportional across the source net tenders
  (`refunded_total / source.grand_total`).
- **Wastage.** Return lines flagged not-restockable skip the SLE restore. Their value posts
  Dr `Restaurant.wastage_account` / Cr the returned line's warehouse account at current WAC,
  keeping the physical bar stock and its ledger value in agreement. New
  `OrderItem.not_restockable` Boolean (default False), settable only on return drafts.
- **Partial returns.** Partiality is the return draft's negative quantities: lines can be
  reduced before submit (draft editing), and the existing cumulative-returned-quantity check
  against `return_against_item` stays authoritative. After a return is SUBMITTED, a new return
  draft may be created for the same source order (the one-active-return rule covers drafts
  only), letting an order be refunded in several passes over time.
- **Permissions.** Return creation and submission remain Manager/Admin only.

**Tests:** `submit_return` posts mirrored refund GL; partial return posts only the refunded
portion; not-restockable lines post wastage and skip the SLE; second return against the same
source is allowed after the first is SUBMITTED; cumulative qty cap still enforced.

### 4.4 Opening Balances and Go-Live Setup (Phase 6)

**Status:** complete — implemented and retired.

**Decisions:**

- A single reviewed opening Journal Entry per fiscal year using the `OPENING` voucher type;
  `submit()` sets `is_opening=True` automatically for that type.
- One selected opening date (must fall inside the enabled fiscal year), one balanced entry, a
  required source/note per balance row (row `remarks` non-empty).
- Duplicate protection: `submit()` atomically rejects a second OPENING JournalEntry for the
  same fiscal year. Amend flow: cancel + amend, never edit.
- Review + submit action: the opening form reuses the Journal Entry form with the voucher type
  locked to OPENING; a read-only review screen precedes the submit confirmation; once
  submitted the entry is immutable like every JE.
- No import wizard and no journal-import screen.
- Go-live prerequisite when RestPOS is the accounting source of truth.

**Tests:** OPENING submit sets `is_opening`; balanced-openings + remark requirements; second
opening JE for the same fiscal year rejected; review screen requires explicit submit; amend
chain works from a cancelled opening.

### 4.5 Cash Shortage and Excess Posting (Phase 6)

**Status:** complete — implemented and retired.

**Decisions:**

- **Accounts.** `Restaurant.cash_shortage_account` (expense) and
  `Restaurant.cash_over_short_account` (income), both nullable. Variance posting is automatic
  only when the account matching the variance sign is configured; otherwise the close shows
  the variance as it does today and no posting occurs.
- **Posting.** Inside `submit_closing_entry`'s atomic block, after the close flips SUBMITTED:
  if `total_short_excess != 0` and the relevant account is set, create a JournalEntry
  (`voucher_type=JOURNAL`) linked via new `POSClosingEntry.variance_journal_entry`
  (OneToOne, SET_NULL). Legs: shortage → Dr shortage account / Cr cash account; excess → Dr
  cash account / Cr over-short account. Cash account = the CASH `ModeOfPayment` GL mapping.
- **Immutability and reversal.** The variance JE is a normal JournalEntry (immutable after
  submit). Cancelling the closing entry reverses the variance JE (mirror negated), preserving
  the close-cancel guards already in place (blocked when a newer open shift exists).
- **Material variance approval.** New `Restaurant.variance_approval_threshold` (Decimal, null =
  no approval gate). When the absolute variance exceeds the threshold, close submission
  requires a non-empty `POSClosingEntry.variance_note` and a Manager/Admin actor; the closing
  form shows the threshold warning before submit.
- **Visibility.** The closing detail page shows the variance and the linked variance JE with
  drill-down, whether or not automatic posting is active.

**Tests:** shortage and excess postings with correct legs; unconfigured account skips posting
but keeps the variance visible; threshold exceeded without note or without manager role is
rejected; cancel reverses the variance JE; closing-cancel guard still applies.

### 4.6 Daily P&L (Phase 7)

**Status:** complete — implemented and retired; current product facts are in `FEATURES.md`, `docs/`, and the code.

**Scope:** a submitted Daily P&L document for one restaurant business day. It is a management
snapshot, not the formal accounting P&L (that is Phase 8, a query over `GLEntry`). Submitting
a Daily P&L **does not post GL**.

**App:** `apps.reports`. Manager/Admin only. Sidebar group **Reports** with Daily P&L and P&L
Settings.

**Statement:** three columns FOOD / DRINKS / TOTAL; percents of gross sales. Gross sales →
round-off → net sales → drink WAC COGS → kitchen consumption (memo) → direct expenses
(electricity, materials, daily-fixed, ad-hoc) → gross profit → prime cost (memo) →
indirects (employee, templates, depreciation, cash variance, ad-hoc) → net profit.

**Models:** `PnLConfiguration` singleton, `PnLMaterial`, `PnLRecurringExpense`, `DailyPnL`,
`DailyPnLMaterialQty`, `DailyPnLAdHoc`, `DailyPnLLine`, `DailyPnLCogsRow`,
`DailyPnLConsumptionRow`. One DRAFT and one SUBMITTED per `business_date`. Amend copies
inputs into a new draft; cancel does not post GL.

**Window:** `[business_date + start_hour, next day + start_hour)`. Orders by
`posting_date`+`posting_time`; consumption recs by `posting_date`; cash variance by
`POSClosingEntry.period_end_date`.

**Computation:** submit snapshots settings and live sources; does not post `GLEntry`. Drink
COGS from settle-time drink SLEs at current WAC (`unit_rate`); food never in COGS; kitchen
consumption (reconciliation at current WAC) is memo only. Employee templates or a per-day
override. Electricity optional (blank = ₦0).

### 4.7 Reports (Phase 8)

**Status:** planned (scope only; detailed decisions to be locked when Phase 8 starts).

**Decisions:**

- Sales reports: today's, daywise, month-wise, item-wise, employee-wise, service-wise,
  time-wise.
- Cancelled invoices, average bill value, POS register.
- Read-only GL report, Trial Balance, and a simple Profit & Loss report over `GLEntry`,
  grouped by account, fiscal year, and posting date, with drill-down to the
  source voucher. Cancelled entries and their reversals are handled consistently.
- No balance sheet and no formal statements.
- Query-based; no persistent aggregates unless needed.

### 4.8 Printing (Phase 9)

**Status:** planned (scope only; detailed decisions to be locked when Phase 9 starts).

**Decisions:**

- Three thermal printers: cashier receipt (USB), kitchen ticket (LAN, static IP), bar ticket
  (LAN, static IP).
- A local Python print agent on the cashier desktop receives jobs from Django via HTTP on
  localhost, formats ESC/POS, and sends to the target printer (TCP for LAN, direct for USB).
- Routing: customer receipt → cashier printer; FOOD tickets → kitchen; DRINKS tickets → bar.
- Printer identity and paper configuration stay on the ProductionUnit (already present).
- Receipt and ticket formats are Django templates producing ESC/POS command strings.
- Settlement auto-prints the receipt without blocking payment; failed prints warn and stay
  reprintable from order history. Per-ticket print status and retry already exist.
- `apps/orders/printing.py` stub is replaced by the real client.

**Models:** PrintJob, PrinterConfig (or ProductionUnit fields, per the final design).

### 4.9 Perpetual Weighted-Average Cost — FIFO → PWAC (Phase 2 rework)

**Status:** complete — implemented and retired; current product facts are in `FEATURES.md`,
`docs/workflows/inventory.md`, and the code. Receipt-first invoice UX is in §4.1.

**Decisions (D1–D8):**

- **D1 — Backdated receipts = full WAC blend at actual cost.** Any receipt blends:
  `new_wac = (old_qty×old_wac + qty×actual)/(old_qty+qty)`. No variance at receipt; `posting_date` is audit only.
- **D2 — Wastage = no warehouse.** Keep `WASTE_DAMAGE` as `StockReconciliation.reason` on a real warehouse, valued at current WAC → existing `Restaurant.wastage_account`.
- **D3 — Opening stock entered rate seeds WAC.** `OPENING_STOCK` posts at user `valuation_rate`; if `Bin qty==0` and the adjustment adds stock, require `valuation_rate` to seed WAC; else current WAC.
- **D4 — GRN at receipt (accrual).** Receipt: `Dr SIH (warehouse asset) / Cr GRNI` @ receipt rate. Stock invoices must link a receipt via `SupplierInvoice.purchase_receipt` and post `Dr GRNI / Cr Payable` @ the same rate. Expense-only invoices need no receipt. No unlinked `Dr SIH / Cr Payable` path. Random market purchase without formal receipt uses `StockEntry MATERIAL_RECEIPT` → `Dr SIH / Cr expense` directly (no GRNI, no invoice).
- **D5 — Dedicated variance account** `Restaurant.inventory_price_variance_account` for **cancellation WAC drift only**. Sale-return variance posts to **COGS**: `variance = qty×(current WAC − original COGS rate)` → Dr COGS if positive, Cr COGS if negative. No `PURCHASE_PRICE` variance type.
- **D6 — Block receipt cancel if downstream financial doc active** — `SupplierInvoice(status=SUBMITTED, purchase_receipt=receipt)` OR `SupplierPayment` allocation against that invoice. Cancel chain: `Payment → Invoice → Receipt`.
- **D7 — Clean slate migration.** No production data. `RunPython` wipes `StockLedgerEntry` + `Bin` (FIFO snapshots) + drops `stock_value, stock_queue, is_cancelled, qty_after_transaction` columns. Docs stay; bins rebuild.
- **D8 — Backdated threshold** is report-only: `posting_date < created_at::date` labels "late entry" for humans; no valuation branch.

**Implemented model:**

- `Bin`: `item, warehouse, actual_qty, valuation_rate (=wac), reserved_qty`. `stock_value` is a derived property (`actual_qty × valuation_rate`); `stock_queue` removed.
- `StockLedgerEntry` (append-only): `item, warehouse, voucher_type, voucher_no, voucher_detail_no, posting_date, quantity (signed), unit_rate, stock_value_change (signed), variance_amount, variance_type (CANCELLATION_WAC | SALE_RETURN), reversal_of_sle (FK nullable), posting_datetime (auto_now_add)`.
- Dropped from SLE: `stock_queue, incoming_rate, outgoing_rate, valuation_rate, stock_value, qty_after_transaction, is_cancelled`.

**Business rules:**

- Sale/consumption/waste: current WAC, outbound `unit_rate=wac`, `stock_value_change=−qty×wac`, WAC unchanged. Negative stock prohibited everywhere.
- Transfer A→B: source `−qty×source_wac`, dest `+qty×source_wac` then dest recalculates WAC; net 0. Cancel: dest `−qty×dest_current_wac`, source `+qty×dest_current_wac`, source recalculates; net 0.
- Reconciliation: `OPENING_STOCK` or `qty==0` + `+qty` → require entered `valuation_rate` to seed WAC; else current WAC.
- Receipt cancellation (D6): blocked if downstream invoice/payment active; else `Cr SIH @ current WAC / Dr GRNI @ original` → diff to `variance_amount` (`CANCELLATION_WAC`) → `inventory_price_variance_account`. No partial.
- Sale cancellation/return: `+qty×current WAC` back to Bin; diff vs original COGS → Dr/Cr COGS (sale-return variance in COGS, not variance account).
- Future-dated transactions rejected: `posting_date > today → ValidationError`.

**GL entries:**

- Receipt: `Dr SIH (warehouse asset) / Cr GRNI` @ `qty×rate`.
- Linked invoice: `Dr GRNI / Cr Payable` @ same rate (rate equality enforced; no variance branch). Expense lines → `Dr Restaurant.default_supplier_expense_account / Cr Payable` (not part of GRNI).
- Stock-entry market purchase (`MATERIAL_RECEIPT`): `Dr SIH / Cr Cash-or-Expense` directly — no GRNI, no invoice.
- Receipt cancellation: `Cr SIH @ current WAC / Dr GRNI @ original` → difference to variance account (`CANCELLATION_WAC`).
- Sale-return variance: `variance = qty×(current WAC − original COGS rate)` → Dr COGS if positive, Cr COGS if negative.

**Settings:** `Restaurant.stock_received_but_not_billed_account` (GRNI, liability) + `Restaurant.inventory_price_variance_account` (expense). Seed defaults in `seed_chart_of_accounts`; forms validate required when inventory active.

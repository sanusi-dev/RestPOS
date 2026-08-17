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
| `accounting` | Chart of accounts, GL entries, journal entries, fiscal years, cost centers | E #57–60 | planned |
| `reports` | Daily P&L, sales reports, trial balance | E #62–63 | planned |
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
| 2 | inventory | A3 | Item master with independent flags, groups, warehouses, immutable FIFO stock ledger, receipts/transfers/reconciliations, purchase receipts, bins, stock reports | Supplier payables (needs Phase 6 GL) | §4.1 | Completed |
| 3 | menu | A2 | Menu, menu items, specials, disable, images, variants, add-ons, seed command | — | n/a | Completed |
| 4 | staff, payments | A4, A5 | Payment modes with default + GL mappings, opening/closing entries, reconciliation, refund netting | — | n/a | Completed |
| 5 | orders | A6, A7, B, C | POS workbench, order lifecycle with stage exits and returns, KOT/BOT tickets with print status, group ordering, audit events, orders control room | — | n/a | Completed |
| 6 | accounting | E #57–60 | — | GL core + order posting, refunds completion, opening balances, cash variance posting | §4.2–4.5 | Planned |
| 7 | reports | E #62 | — | Daily P&L document with amendments and departmental split | §4.6 | Planned |
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

**Status:** planned. Implementation lands after Phase 6 GL posting is available, since
invoice and payment posting depend on it.

**Decisions:**

- A `Supplier` master separate from the `supplier_name` string on `PurchaseReceipt`; the
  receipt keeps its free-text field for quick entry and optionally links to a Supplier.
- `SupplierInvoice` documents with lines linked to received stock or expenses, submitted and
  cancelled like other financial documents.
- Accounts-payable balances per supplier; `SupplierPayment` entries with payment-to-invoice
  allocation rows.
- Posting: purchases record Dr Stock-in-Hand / Cr Accounts Payable on the invoice; Dr
  Accounts Payable / Cr Bank (or Cash) on payment. Cancellation reverses posted entries.

**Models:** Supplier, SupplierInvoice, SupplierInvoiceItem, SupplierPayment,
payment-allocation rows.

### 4.2 Accounting / GL (Phase 6)

**Status:** planned.

**Scope decisions (locked):**

1. Single-tier posting: the Order is the accounting document. GL posts at order settle and
   reverses at order cancel. No consolidated sales invoices at shift close; the close keeps
   consuming aggregates only.
2. No party/receivable ledger. All sales are walk-in cash/bank.
3. No tax GL. There is no tax system.
4. COGS at settle from the FIFO outgoing values of the settle-time drink stock deductions.
5. Inventory documents (purchase receipts, stock entries, reconciliations) post no GL
   initially.
6. Return orders post no GL in the GL core; refund GL posts in refunds completion (§4.3),
   within the same phase.
7. Write-off is a manual journal-entry voucher type (`WRITE_OFF` + `write_off_amount`).
8. Amendment chain (`amended_from`) applies to JournalEntry only.

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

**CostCenter**

| Field | Type |
|---|---|
| `name` | CharField(100) unique |
| `parent` | FK self, SET_NULL, null=True |
| `is_group` | Boolean, default False |
| `disabled` | Boolean, default False |

Same tree rules as LedgerAccount.

**GLEntry**

| Field | Type | Notes |
|---|---|---|
| `posting_date` | DateField | |
| `account` | FK LedgerAccount, PROTECT | leaf accounts only |
| `cost_center` | FK CostCenter, SET_NULL, null=True | optional |
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
| `voucher_type` | choices JOURNAL/CASH/BANK/WRITE_OFF/OPENING, default JOURNAL | |
| `posting_date` | DateField | |
| `reference_no` / `reference_date` | CharField(50) / DateField null | |
| `remark` | TextField blank | |
| `status` | DRAFT/SUBMITTED/CANCELLED | |
| `total_debit` / `total_credit` | Decimal(14,2), editable=False | recomputed on save |
| `difference` | Decimal(14,2), editable=False | must be 0 to submit |
| `write_off_amount` | Decimal(12,2), default 0 | required non-zero when voucher_type=WRITE_OFF |
| `is_opening` | Boolean, default False | |
| `amended_from` | FK self, SET_NULL, null=True | amendment chain |

Methods: `submit()` (atomic; rows may not mix debit and credit, no duplicate
account+cost_center rows, difference 0, total > 0; posts one GLEntry per row; a
`voucher_type=OPENING` entry sets `is_opening=True` automatically), `cancel()` (atomic;
mirrored negated entries, originals marked `is_cancelled`), `amend()` (only from CANCELLED;
copies into a new DRAFT linked via `amended_from`).

**JournalEntryAccount**

| Field | Type |
|---|---|
| `journal_entry` | FK JournalEntry, CASCADE |
| `account` | FK LedgerAccount, PROTECT |
| `cost_center` | FK CostCenter, SET_NULL, null=True |
| `debit` / `credit` | Decimal(14,2), default 0 |
| `remarks` | CharField(200) blank |

##### Changes outside accounting

- `payments.PaymentGLMapping.default_account`: CharField → FK LedgerAccount, PROTECT;
  leaf-only validation. Data migration matches existing strings by name (case-insensitive),
  creating a missing leaf account under Assets (Cash/Bank by mode type).
- `settings.Restaurant` gains nullable FKs: `default_income_account`,
  `default_expense_account`, `round_off_account`, `account_for_change_amount`,
  `write_off_account`, `write_off_cost_center`, `cost_center`, `wastage_account`
  (consumed by §4.3), `cash_shortage_account`, `cash_over_short_account`,
  `variance_approval_threshold` (Decimal, consumed by §4.5). Settlement enforces the
  ones it needs; the settings form gains an Accounting section.
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
`voucher_type="Order"`, `voucher_no=invoice_number`, `posting_date`, resolved fiscal year, and
the Restaurant cost center when set.

| Leg | Dr | Cr | Amount | Account resolution |
|---|---|---|---|---|
| Income | — | income account | Σ item amounts per account | `ItemGroup.income_account` → `ProductionUnit.income_account` (by line department) → `Restaurant.default_income_account` (required — settle raises if empty) |
| Payment | payment account | — | per OrderPayment `amount`, reduced by change on the row whose account equals `Restaurant.account_for_change_amount` | `ModeOfPayment` GL mapping (required) |
| Round-off | — | `Restaurant.round_off_account` | `rounding_adjustment` (may be negative) | required when non-zero |
| COGS | expense account | `order.stock_warehouse.account` | FIFO outgoing value of the settle-time deductions, per account | `ItemGroup.expense_account` → `Restaurant.default_expense_account` (required when stock items exist) |

`against` holds the balancing account names; entries sharing account/against/fiscal
year/cost center merge. Order cancel posts mirrored negated entries, originals
`is_cancelled=True`.

##### Frontend

All pages extend the backoffice base; the nav gains an Accounting section (Chart of Accounts,
Journal Entries, GL Entries, Fiscal Years, Cost Centers). Chart of accounts is a tree page with
HTMX expand/collapse; journal entries use the existing formset add/remove row pattern with
submit/cancel/amend POST buttons; GL entries are a read-only filtered table; fiscal years and
cost centers are simple CRUD pages.

##### Seeds

`seed_chart_of_accounts` (idempotent): Assets → Cash Account, Bank Accounts → Electronic
Account; Inventory stock leaves per warehouse; Income → Food Sales + Drinks Sales; Expenses →
Cost of Goods Sold + Round Off; Equity → Owner's Equity. Creates Kitchen/Bar cost centers, the
current-year fiscal year, and wires production-unit income accounts, warehouse accounts,
Restaurant defaults, and payment GL mappings.

##### Activation and rollout

- There is no accounting off-switch. Once the phase ships, order settlement posts GL —
  settlement fails closed when the required account chain is missing (no silent
  gap between sales and the books).
- Go-live sequence: run `seed_chart_of_accounts` (idempotent) → run `seed_pos_setup`
  (which now invokes the chart seed first) → configure the Restaurant accounting FKs in
  settings → the data migration in `payments` converts existing `PaymentGLMapping` strings
  to FK values during `migrate`. Checkout works only after this sequence completes.

##### Tests

- `test_models.py` — account tree rules, fiscal year rules + `get_for`, cost center tree, GL
  immutability.
- `test_journal_entry.py` — balanced submit, unbalanced/mixed-row/duplicate rejections,
  frozen/disabled/group account rejections, cancel reversal, amend chain, write-off voucher.
- `test_order_gl.py` — settle legs incl. departmental income split, change reduction,
  rounding, COGS; cancel reversal; missing account config raises; fiscal year guard raises.
  (Return-order GL is covered by §4.3 tests.)
- `test_payment_gl_mapping.py` — FK + leaf-only validation.
- `test_views.py` — backoffice gate and CRUD flows.
- Existing orders/staff suites gain a shared accounting setup helper because settlement now
  requires the account chain.

### 4.3 Refunds Completion (Phase 6)

**Status:** planned — detailed decisions locked below.

**Decisions:**

- **Refund GL on return submit.** `submit_return` posts refund GL inside its own atomic block
  after the return flips SUBMITTED: mirror-negated entries of the source order's settle legs
  (income, payment, round-off, COGS) for the refunded portion only, carrying the return's
  invoice number as `voucher_no="Order"`. The mirror exactly negates the source set, so
  balances cannot drift. Restockable lines restore the bin via the existing "POS Return" SLE;
  the COGS leg reversal credits the warehouse account for the restored value.
- **Wastage.** Return lines flagged not-restockable skip the SLE restore. Their value posts
  Dr `Restaurant.wastage_account` / Cr the returned line's warehouse account at the settle-time
  valuation rate, keeping the physical bar stock and its ledger value in agreement. New
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

**Status:** planned — detailed decisions locked below.

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

**Status:** planned — detailed decisions locked below.

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

**Status:** planned (scope only; detailed decisions to be locked when Phase 7 starts).

**Decisions:**

- A `DailyP&L` document per day: gross sales → COGS → direct expenses (electricity meter
  readings, materials/consumables, ad-hoc) → gross profit → indirect expenses (rent,
  insurance, depreciation, employee costs) → net profit. Every line shows naira and % of
  gross sales.
- COGS: drinks follow actual POS stock deductions and valuation; food has no BOM-derived cost
  — Kitchen consumption reconciliations are reported alongside FOOD sales for comparison.
- Amendment (`amended_from`) reversal chain for corrected submissions.
- Extended-hours day boundary for venues operating past midnight.
- Departmental FOOD/DRINKS split of the P&L.

**Models:** DailyP&L, P&LLineItem, P&LAmendment.

### 4.7 Reports (Phase 8)

**Status:** planned (scope only; detailed decisions to be locked when Phase 8 starts).

**Decisions:**

- Sales reports: today's, daywise, month-wise, item-wise, employee-wise, service-wise,
  time-wise.
- Cancelled invoices, average bill value, POS register.
- Read-only GL report, Trial Balance, and a simple Profit & Loss report over `GLEntry`,
  grouped by account, fiscal year, posting date, and cost center, with drill-down to the
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

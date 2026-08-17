# RestPOS — Implementation Plan

> This document is the implementation plan for RestPOS. It has two tiers:
>
> 1. **High-level roadmap (Sections 1–5)** — written once, covers all 8 apps at a strategic
>    level. Read this to understand the full project scope and build sequence.
> 2. **Detailed plans (Section 6)** — written incrementally, one per phase, just before
>    implementation. Each contains model fields, views, templates, tests, and reference files.


---

## 1. Project Overview

**RestPOS** is a restaurant POS and management system for a Nigerian restaurant, built with
Django + HTMX + Tailwind CSS + Alpine.js. It covers counter-based ordering, kitchen/bar
ticket printing, payments, inventory, daily P&L, and departmental sales split (food vs drinks).

**Scope:** local network only. Django runs on the cashier desktop. All operations work
without internet. The owner accesses the back office from any device on the same WiFi.

**Tech stack:**

| Layer | Technology |
|---|---|
| Backend | Django 6.0+ (Python 3.14) |
| Frontend | Django templates + HTMX + Tailwind CSS v4 + Alpine.js + SweetAlerts |
| Database | PostgreSQL |
| Package manager | uv (Python), npm (JavaScript) |
| Task queue | Celery + Redis (scheduled tasks only) |
| Printing | Local Python print agent (ESC/POS over LAN/USB) |

**What is NOT used:** Django REST Framework (installed from boilerplate but unused),
Vue, React, Socket.io, DaisyUI (exists in boilerplate templates but not used in new code).

**Reference codebases:** `references/erpnext-develop/` (ERPNext) and `references/ury-develop/`
(URY restaurant layer) are READ ONLY. Every feature is ported from these references before
being implemented in Django.

---

## 2. App Architecture

### Apps

The project is organised into 8 Django apps under `restpos/apps/` (plus planned
apps for the unbuilt phases):

| App | Responsibility | FEATURES.md sections |
|---|---|---|
| `settings` | Restaurant settings (singleton), production units, user roles | A1, A3, A4 |
| `inventory` | Item master, item groups, warehouses, stock ledger, stock entries, valuation | A12 |
| `menu` | Menu definition, menu items, variants, add-ons, pricing | A2 |
| `staff` | POS opening/closing entries, cashier shifts, session management | A9, A17 |
| `payments` | Payment modes, GL mapping, change calculation, rounding | A10 |
| `orders` | Orders, order items, customer cards, tickets, cancellation, refunds | A6, A7, A18 |
| `printing` *(planned)* | Print agent client, ESC/POS formatting, ticket/receipt formats, printer config | A8 |
| `accounting` *(planned)* | Chart of accounts, GL entries, journal entries, fiscal year, cost centers, write-off | A13, A16 |
| `customers` *(deferred)* | Customer master, customer groups, credit limits | A11 |
| `coupons` *(deferred)* | Coupon codes, pricing rules, cashier % discount | A13 #130–131, A10 #98–99 |
| `pnl` / `reports` *(planned)* | Daily P&L, sales/stock/customer reports, departmental split | A14, A15, C |

### Dependency Graph

```
settings → inventory → menu → staff ↘
                      payments core ↗    orders → accounting → daily P&L → reports
                                                                 ↑
                                          refunds completion ←──┘

orders → printing (leaf — depends only on orders; built last)
```

**Build order reasoning:**
- `settings` first — every other app references the `Restaurant`
- `inventory` before `menu` — menu items reference the Item master
- `menu` before `orders` — orders contain menu items
- `payments core` is standalone (no deps); built before `staff` because `OpeningPayment.mode_of_payment` is a FK to `ModeOfPayment`
- `staff` needs `settings` (Restaurant) and `payments core` (ModeOfPayment); built before `orders` because orders stamp the active shift
- `orders` is the central app — needs settings, menu, staff, and payments
- `accounting` (Phase 6) needs payments (migrate `PaymentGLMapping` → FK), orders (post sales GL at settle), inventory (COGS valuation); shift close consumes aggregates only — no GL at close (§6.8.2.1)
- `daily P&L` (Phase 7) needs accounting + inventory (COGS) + orders (sales)
- `reports` (Phase 8) needs everything
- `refunds completion` (Phase 6) extends orders/payments/inventory/accounting
- `printing` (Phase 9) needs orders (ticket data to format and print); built last — leaf dependency, does not gate the accounting chain
- `customer management` (deferred) — would be needed by orders (link to a Customer instead of a string); parked after the core phases
- `coupon engine` (deferred) — would extend orders/payments; parked after the core phases

### Cross-Cutting Concerns

- **Base model:** All models extend `apps.utils.models.BaseModel` (adds `created_at`, `updated_at`)
- **User model:** `apps.users.models.CustomUser` (extends `AbstractUser`, adds `avatar`)
- **Money:** All monetary values use `DecimalField`, never `FloatField`
- **Submit/cancel workflow:** Financial documents go through Draft → Submitted → Cancelled.
  Submitted records are immutable. Corrections create reversal entries, not edits.
- **Template partials:** Django 6.0 `{% partialdef %}` / `{% partial %}` for reusable fragments
  and HTMX responses. `{% include %}` only for genuinely shared cross-template fragments.
- **HTMX:** All dynamic interactions use HTMX attributes. No inline JavaScript.
- **Alpine.js:** Client-side interactivity (dropdowns, modals, toggles) that doesn't need server.
- **SweetAlerts:** Toast notifications and confirmation dialogs.
- **Tailwind CSS:** All styling. No DaisyUI in new code.
- **Roles:** Two custom roles — RestPOS Manager, RestPOS Cashier.

---

## 3. Build Sequence

| Phase | App | FEATURES.md sections | Key models | Dependencies | Status |
|---|---|---|---|---|---|
| 1 | settings | A1, A3 | Restaurant, ProductionUnit | None | complete (settings merged into Restaurant singleton — §6.14) |
| 2 | inventory | A12; scope recs §6 (supplier payables, plan §6.28) | Item, ItemGroup, Warehouse, StockLedgerEntry, StockEntry, StockReconciliation, UOM, Bin; later Supplier, SupplierInvoice(+items), SupplierPayment | settings | complete for stock (§6.20 rules); supplier payables planned (§6.28), not implemented |
| 3 | menu | A2 | Menu, MenuItem, ItemAddOn, ItemVariant | inventory | complete (PriceList/ItemPrice removed in §6.17; POS reads MenuItem.rate) |
| 4 | staff (incl. payments core) | A9, A17; A10 (partial) | ModeOfPayment, PaymentGLMapping, POSOpeningEntry, POSClosingEntry, OpeningPayment, ClosingPayment | settings | complete (payments core folded in; single shared shift; closing sums OrderPayment totals per mode) |
| 5 | orders | A6, A7, A18 | Order, OrderItem, OrderPayment, KOT, KOTItem, OrderAuditEvent, OrderSequence | settings, menu, staff, payments | complete (POS workbench, continuous numbering, tickets, drinks-only stock, returns, paid-order ticket guarantee §6.23, stage exits §6.24) |
| 6 | accounting / GL | A13, A16 (partial); scope recs §1, §3 | LedgerAccount, GLEntry, JournalEntry, FiscalYear, CostCenter; refunds GL (§6.11), opening-balance JE (§6.25), shift-close variance posting (§6.27) | payments, orders, staff, inventory | planned — detailed plan in §6.8 (2026-08-15); refunds completion, opening balances, and variance posting fold in here |
| 7 | daily P&L | A14, C | DailyP&L, P&LLineItem, P&LAmendment, departmental P&L split | all apps | not started |
| 8 | reports | A15, C; scope recs §4 | Sales reports, cancelled invoices, stock reports, POS register, departmental daily reports; GL report + Trial Balance + simple P&L (plan §6.26) | all apps | not started — trial balance / financial statements fold in (plan §6.26) |
| 9 | printing | A8 | PrintAgent client, ESC/POS formatter, PrinterConfig | orders | not started (stub `apps/orders/printing.py`) — built last; leaf dependency, does not gate the accounting chain |
| — | customer management (deferred) | A11 | Customer, CustomerGroup, credit limits, customer search/create from POS, favourite items | orders | deferred — added later after the core phases; only `Order.customer_name` (string, default "Walk-in Customer") exists today |
| — | coupon engine (deferred) | A13 #130–131 | CouponCode, pricing rules; cashier % discount | orders, payments | deferred — added later; no discount/coupon system exists today

### Remaining work by phase

Snapshot of what is not yet implemented, keyed to the merged phases above. **planned** =
detailed plan exists in §6, ready to implement; **unplanned** = stub only. Phases 1, 3, and 4
have no pending work.

| Phase | Pending work | Plan state |
|---|---|---|
| 2 | Supplier payables | planned (§6.28) |
| 5 | Order stage exits (delete / cancel / settle-print / return) | planned (§6.24), implementation underway |
| 6 | Accounting/GL core, opening balances, variance posting | planned (§6.8, §6.25, §6.27) |
| 6 | Refunds completion (GL reversal, wastage, partial returns) | **unplanned** — §6.11 stub |
| 7 | Daily P&L | **unplanned** — §6.9 stub |
| 8 | Reports core | **unplanned** — §6.10 stub |
| 8 | Trial balance / financial statements | planned (§6.26) |
| 9 | Printing | **unplanned** — §6.12 stub |
| — | Customer management, coupon engine (deferred) | unplanned by design (§6.13) |

### Status values

- **not started** — no work done yet
- **planned** — detailed plan written in Section 6, ready to implement
- **in progress** — implementation underway
- **complete** — implementation done, tests passing, lint clean

---

## 4. App Summaries

### settings (Phase 1)

**Scope (current):** `Restaurant` singleto  (company, address, `invoice_series_prefix`,
`active_menu`, `currency`, `default_warehouse` = Bar/POS deduction, `store_warehouse` = central
Store, `pos_allow_full_history`, `max_open_drafts`), and `ProductionUnit` (Kitchen FOOD / Bar
DRINKS with `warehouse`, printer fields, `block_takeaway_kot`). The single-location cleanup
(§6.14) removed Branch, Room, Table, UserRoomAssignment, POSProfile(+Users/Payments), and
TaxTemplate/TaxRate entirely.

**Key reference doctypes:** URY Restaurant, URY Production Unit, URY Printer Settings

### inventory (Phase 2)

**Scope (current):** Item master (products), item groups (flat categories), warehouses, stock
ledger entries (immutable movement records), stock entries (manual movements), stock
reconciliation, valuation methods. Single UOM per item — no conversions needed. Per §6.20:
`Item` has independent `is_stock_item` / `is_sales_item` / `is_purchase_item` flags; receipts
post to `Restaurant.store_warehouse`; Material Transfer is restricted Store→department target;
`StockReconciliation` has a required `reason` (PHYSICAL_COUNT / CONSUMPTION / WASTE_DAMAGE /
CORRECTION); Material Issue was removed. Batch tracking, product bundles, barcodes, reorder
levels all removed (unnecessary for restaurant use).

**Key models:** Item, ItemGroup, Warehouse, StockLedgerEntry, StockEntry, StockEntryDetail,
StockReconciliation, StockReconciliationItem, PurchaseReceipt, PurchaseReceiptItem, Bin, UOM

**Key reference doctypes:** ERPNext Item, Item Group, Warehouse, Stock Ledger Entry, Stock Entry,
Stock Reconciliation, Purchase Receipt, UOM Conversion, Sales BOM

### menu (Phase 3)

**Scope (current):** Menu definition (single menu — no branch), menu items (links Item master to a
selling rate), special dish flag, item disable, item images, POS variants (Quarter/Half/Full),
POS add-ons. ProductBundle, PriceList, and ItemPrice were removed (§6.17 — the POS resolves
prices from `MenuItem.rate` directly).

**Key models:** Menu, MenuItem, ItemAddOn, ItemVariant

**Key reference doctypes:** URY Menu, URY Menu Item, URY Menu Course, Item Add On, ERPNext Item
Variant

### payments core (Phase 4)

**Scope (current):** Payment modes (Cash, Bank, General, Phone) as a flat master, GL account
mapping (account name as a CharField — Phase 6 introduces a real `LedgerAccount` and migrates to
a FK). `ModeOfPayment` has `enabled` (accept this mode) and `is_default` (exactly one — §6.14);
`PaymentGLMapping` is OneToOne per mode (company field dropped). Change calculation, rounding,
and split-payment UI live in the orders app (Phase 5).

**Key models:** ModeOfPayment, PaymentGLMapping

**Key reference doctypes:** ERPNext Mode of Payment, Mode of Payment Account, URY POS Profile
payment-method resolution

### staff (Phase 4)

**Scope (current):** Single shared cashier shift (FEATURES.md #85) — no branch field, no
POSProfile. POS opening entries (shift start with float per payment method), POS closing entries
(shift end with reconciliation between opening float, expected sales, and cashier-counted
amounts). Manager + Cashier roles can both open/close. `POSClosingEntry.submit()` (Phase 5) sums
`OrderPayment.amount` per `mode_of_payment` within the shift window into `expected_amount`
(excluding returns, matching the §6.7 checklist). The shift opens inline from the POS screen
(§6.19).

**Key models:** POSOpeningEntry, POSClosingEntry, OpeningPayment, ClosingPayment

**Key reference doctypes:** ERPNext POS Opening Entry, POS Closing Entry, URY User, Role
Permitted, URY hooks for opening/closing validation

**Simplifications (documented in §6.5 Deviations):** no multi-cashier / Sub POS Closing,
no async / Queued/Failed consolidation, no daily-close "5 AM day boundary" check, no Order FK
on the closing entry totals.

### orders (Phase 5)

**Scope (current):** The central app. Counter-based orders (no tables — docket-to-cashier
workflow), order items, customer cards / group ordering (guest count, active card state,
customer index on items), continuous sequential order numbering (§6.15, `OrderSequence`),
kitchen/bar ticket creation and cancellation (§6.17, `KOT`/`KOTItem` with `ticket_type` and
`print_status`), drinks-only stock reservation/deduction (§6.20), settlement (split payment,
rounding, change), cancellation (with cancellation tickets), returns (is_return + return_against
FK, negative items), POS workbench (three-column layout, catalogue search, add-on dialog — §6.21),
POS shell navigation (§6.22), and the backoffice orders control room (§6.18). No tax system,
no table transfer, no waiter roles, no KOT diffing (a sent order is cancelled and replaced).

**Key models:** Order, OrderItem, OrderPayment, KOT, KOTItem, OrderAuditEvent, OrderSequence

**Phase 5 completion checklist — shift close integration (implemented):**
`POSClosingEntry.submit()` already sums `OrderPayment.amount` per `mode_of_payment` for orders
within the shift's `period_start_date`..`period_end_date` window, filtering:
- `status=SUBMITTED` — excludes CANCELLED and DRAFT orders automatically
- `is_return=False` — return orders refund cash and should not add to expected drawer totals

Cancelled orders retain all original payment rows for audit — cancel flips status without
mutating any payment data.

**Key reference doctypes:** ERPNext POS Invoice, POS Invoice Item, URY Order, URY Order Item, URY
KOT, URY KOT Items, URY hooks for order/KOT/invoice events

### accounting (Phase 6)

**Scope (current):** The General Ledger. `LedgerAccount` chart of accounts (flat FK tree),
`GLEntry` (immutable, reversal-only), `JournalEntry` + rows (manual balanced entries, write-off
voucher type, amendment chain), `FiscalYear`, `CostCenter`. Sales + COGS GL posts at order
settle and reverses at cancel; `PaymentGLMapping.default_account` migrates CharField → FK.
No tax GL, no party/receivable legs, no GL for inventory documents or returns yet (§6.8.2).

**Key models:** LedgerAccount, GLEntry, JournalEntry, JournalEntryAccount, FiscalYear, CostCenter

**Key reference doctypes:** ERPNext Account, GL Entry, Journal Entry, Journal Entry Account,
Cost Center, Fiscal Year; GL composer + `make_reverse_gl_entries`; URY POS invoice/closing hooks

### daily P&L (Phase 7)

**Scope:** `DailyP&L` document per day: gross sales → COGS → direct expenses (electricity
meter readings, materials/consumables, ad-hoc) → gross profit → indirect expenses (rent,
insurance, depreciation, employee costs) → net profit, each line as naira + % of gross sales.
P&L amendment (`amended_from` reversal), extended hours / day boundary, and departmental
FOOD/DRINKS split (per C).

**Key models:** DailyP&L, P&LLineItem, P&LAmendment

**Key reference doctypes:** URY Daily P&L, URY P&L doctypes (materials, COGS, expenses)

### reports (Phase 8)

**Scope:** Sales reports (today's, daywise, month-wise, item-wise, employee-wise,
service-wise, time-wise), cancelled invoices, average bill value, customer data + repeated
customers, stock ledger report, stock balance report, stock ageing report, POS register,
customer credit balance, departmental daily reports (C).

**Key models:** query-based (no persistent aggregates unless needed)

**Key reference doctypes:** ERPNext Sales Invoice reports, Stock Ledger reports, URY reports

### refunds completion (Phase 6)

**Scope:** Completing the refund flow from A18. Return order (is_return + return_against) already
implemented in Phase 5 — creates draft return with negative items/payments, stock restoration on
submit. Phase 6 adds: explicit refund payment entries (reversal GL posting), wastage posting
option, partial return support (adjust qty in return draft before submit), refund permission
(Manager only, already enforced). Cross-app: touches orders, payments, inventory.

**Key models:** Order, OrderItem, OrderPayment, StockLedgerEntry — Phase 5 return orders already handle the core data model; Phase 6 layers in standalone refund entries if needed.

**Key reference doctypes:** ERPNext Payment Entry (reversal), Stock Ledger Entry (positive entry)

---

### printing (Phase 9)

**Scope:** Three thermal printers (cashier USB, kitchen LAN, bar LAN), Python print agent
(localhost HTTP → ESC/POS → printer), print job routing, print status update, printer
configuration (IP in DB on production unit), print formats (receipt, kitchen ticket, bar ticket).

**Key models:** PrintJob, PrinterConfig (may live on ProductionUnit in settings)

**Key reference doctypes:** URY Printer Settings, Network Printer Settings (Frappe core), URY print
hooks

### customer management (deferred)

**Scope:** `Customer` master (name, type, mobile, group, territory, image), `CustomerGroup`,
credit limits, customer search/create from POS, favourite items. Orders link to a Customer
instead of a bare `customer_name` string (walk-in default retained). **Deferred** — added
later, after the core phases (8–12) are complete.

**Key models:** Customer, CustomerGroup

**Key reference doctypes:** ERPNext Customer, Customer Group, Customer Credit Limit

### coupon engine (deferred)

**Scope:** Coupon codes (#131) and pricing rules (#130), plus the cashier % discount
(#98–99) dropped from the POS. **Deferred** — added later, after the core phases; the POS
currently has no discount path.

**Key models:** CouponCode, pricing rule

**Key reference doctypes:** ERPNext Coupon Code, Pricing Rule


---

## 5.5 Cross-cutting UI Conventions

> **Backoffice sidebar structure** (settled in the Phase 4 follow-up):
> - **Backoffice group** (Manager/Admin only): Dashboard, Settings, Inventory, Menu
> - **POS sub-header** (under Backoffice): Payments, Shifts (the planned POS Profile + POS
>   Settings section was removed in §6.14 — settings live under Settings)
> - **Quick Access group**: Launch POS, Sign out
> - The shift item is labelled **"Shifts"** (not "Staff") to avoid colliding with
>   `settings:staff_list` (role assignment, surfaced in the Settings dashboard as the
>   "User Roles" card)
>
> **Main backoffice dashboard** (`/backoffice/dashboard/`) follows the **ERPNext Home pattern**:
> a navigator, NOT a status board. Structure: "Your Shortcuts" row (4 quick-action buttons)
> + "Masters & Setup" grid (4 grouped link cards: Menu, POS, Inventory, Setup). No live
> operational panels — those live on per-app dashboards (Staff dashboard for shifts, Inventory
> dashboard for low stock). No charts/number cards on Home. Analytics will live on a separate
> `/backoffice/operations-dashboard/` page in Phase 5+ once orders and reports exist.
>
> **ERPNect vs RestPOS deviation:** ERPNext puts Mode of Payment in the Accounts Setup workspace
> (configuration), not in the POS section. RestPOS groups it under POS because that's
> the only place it's used (shift floats) and there's no separate Accounts app. Documented
> in `apps/web/views.py` and `templates/web/app/app_base.html` code comments.

---

## 6. Detailed Plans

### 6.1–6.7 Completed phase plans (archived)

Implemented and merged. Historical plans — the current product fact is in §4 App Summaries
and AGENTS.md; verbatim copies in `docs/archive/PLAN-history.md`.

| § | Plan | Outcome |
|---|---|---|
| 6.1 | Settings App — Round 1 (Branch, Room, Table, Restaurant, UserRoomAssignment) | complete; Branch/Room/Table/UserRoomAssignment removed in §6.14 |
| 6.1b | Service Layer Refactor | complete; order/staff workflows moved to service modules |
| 6.2 | Inventory App (Item, Warehouse, StockLedgerEntry, StockEntry, reconciliation, receipts) | complete; receipts/transfers/reconciliation rules revised by §6.20 |
| 6.3 | Menu App (Menu, MenuItem, ItemAddOn, ItemVariant) | complete; PriceList/ItemPrice removed in §6.17 |
| 6.4 | Payments Core (ModeOfPayment, PaymentGLMapping) | complete; `is_default` added in §6.14 |
| 6.5 | Staff App (POSOpeningEntry, POSClosingEntry, floats) | complete; branch/profile FKs removed in §6.14; close sums order payments per mode |
| 6.6 | Settings Round 2 (POSProfile, TaxTemplate, ProductionUnit) | complete; POSProfile/TaxTemplate removed in §6.14 — only ProductionUnit survives |
| 6.7 | Orders App (Order, KOT, settle/cancel, returns, POS workbench) | complete; superseded by §6.14–§6.23 where they conflict |

---
### 6.8 Accounting / GL (Phase 6)

**Status:** planned — detailed plan written 2026-08-15, ready to implement.

**FEATURES.md sections:** A13 #132 (GL entries on sales), #133 (write-off, partial), #134 (cost
center), #135 (fiscal year), #136 (journal entry); A16 #167 (amendment chain, JournalEntry only).

**Dependencies:** payments (migrate `PaymentGLMapping.default_account` CharField → FK), orders
(settle/cancel GL hooks), inventory (COGS valuation from FIFO, `Warehouse.account` /
`ItemGroup.*_account` FKs), settings (`Restaurant`/`ProductionUnit` account FKs). Staff shift
close needs no change — it consumes aggregates only and posts no GL (see §6.8.2.1).

**Key models:** LedgerAccount (chart of accounts), GLEntry, JournalEntry + JournalEntryAccount,
FiscalYear, CostCenter.

**Reference doctypes consulted:**
`references/erpnext-develop/erpnext/accounts/doctype/account/account.{json,py}`,
`gl_entry/gl_entry.{json,py}`, `journal_entry/journal_entry.{json,py}`,
`cost_center/cost_center.json`, `fiscal_year/fiscal_year.json`,
`mode_of_payment/mode_of_payment.py`,
`pos_invoice/pos_invoice.py`, `sales_invoice/sales_invoice.py`,
`sales_invoice/services/gl_composer.py`, `pos_closing_entry/pos_closing_entry.py`,
`references/ury-develop/ury/ury/hooks/ury_pos_invoice.py`,
`references/ury-develop/ury/ury/hooks/ury_pos_closing_entry.py`.

#### 6.8.1 Reference findings

- **ERPNext POS Invoice posts GL on submit** (`sales_invoice.py` `make_gl_entries` →
  `SalesInvoiceGLComposer.compose`): Dr payment-mode default account per payment row, Cr income
  account per item (resolved from Item Group → company default), Cr tax accounts, Dr expense
  (COGS) / Cr stock-in-hand (warehouse account) when `update_stock`, Cr round-off account for
  `rounding_adjustment` (`gl_composer.py:626-675`). Change handling: by default
  (`POS Settings.post_change_gl_entries = 0`) the payment row whose account equals
  `account_for_change_amount` is reduced by `change_amount` instead of posting a separate
  change entry (`gl_composer.py:473-522`).
- **Cancel posts mirror reversals, never edits** (`make_reverse_gl_entries`): new negated
  entries with `is_cancelled=1` on the originals.
- **URY posts nothing extra** — `ury_pos_invoice.py` / `ury_pos_closing_entry.py` hooks do not
  create GL; URY rides on core POS Invoice GL. No consolidation in URY: `sub_pos_invoices` is
  a multi-cashier aggregation child, not a GL consolidation.
- **POS Closing Entry does not post GL** in ERPNext either; consolidation (#127) is an optional
  ERPNext (Nigeria) feature for named-customer invoices, absent from URY.
- **GL Entry validation** (`gl_entry.py` `validate`): exactly one of debit/credit must be
  non-zero; posting date must fall in a fiscal year (`validate_and_set_fiscal_year`); account
  must be a leaf, not disabled, not frozen (`validate_account_details`); GL entries are never
  edited — only cancelled/reversed.
- **Journal Entry validation** (`journal_entry.py`): rows may not carry both debit and credit
  (`set_total_debit_credit`); `total_debit - total_credit` must be 0
  (`validate_total_debit_and_credit`); `amended_from` links the amended copy.
- **Account validation** (`account.py` `validate`): parent must exist, be a group, and not be
  the account itself; `root_type`/`report_type` inherit from parent, roots set them explicitly;
  groups cannot be disabled while they have children (`validate_disabled`); a leaf cannot have
  children (`validate_group_or_ledger`).

#### 6.8.2 Scope decisions (locked)

1. **Single-tier posting — the Order is the accounting document.** GL posts at order settle
   and reverses at order cancel, mirroring ERPNext POS Invoice `on_submit`/`on_cancel`.
   FEATURES #127 (consolidated Sales Invoices at shift close) is deferred: it is an optional
   ERPNext compliance feature that URY does not implement; the shift close keeps consuming
   aggregates only. *(Deviation from FEATURES #127, matching URY.)*
2. **No party ledger.** No `party`/`party_type`/receivable legs on GL entries or journal rows —
   customer management (A11) is deferred, all sales are walk-in cash/bank. *(Deviation from
   ERPNext GL Entry fields.)*
3. **Tax GL deferred.** TaxTemplate/TaxRate were removed in §6.14; no tax system exists. A13
   #128/#129 stay deferred. *(Deviation — no tax accounts in chart seed.)*
4. **COGS at settle** from the FIFO outgoing values of the "POS Order" stock deductions created
   in the same transaction — perpetual-inventory-at-sale, as ERPNext does with `update_stock`.
5. **Inventory documents post no GL in Phase 6** (purchase receipts, stock entries,
   reconciliations). Deferred to Phase 7 alongside daily P&L; Phase 6 books therefore cover
   sales-side entries only. *(Deviation — documented.)*
6. **Return orders post no GL in Phase 6.** A submitted return has negative items but no
   refund payment; refund GL arrives with Phase 6 refunds. *(Deviation — documented.)*
7. **Write-off (A13 #133) as manual JE type.** `voucher_type=WRITE_OFF` + `write_off_amount`
   field; the GL comes from the JE rows themselves. Auto write-off of small receivable balances
   needs the customer ledger (deferred). The `Restaurant.write_off_account` /
   `write_off_cost_center` FKs land now (from the §6.14-removed POSProfile) but are consumed by
   the JE workflow, not by orders.
8. **Amendment chain (A16 #167) for JournalEntry only** in Phase 6 — `amended_from` + amend
   action copying a cancelled JE into a new draft. Order/Payment amendment stays deferred.
9. **Track changes (A16 #168) for accounting docs deferred** — `OrderAuditEvent` covers orders
   already; JE audit events are a later phase.

#### 6.8.3 New app: `apps/accounting`

Registered in `restpos/settings.py`, URL namespace `accounting` under
`backoffice/accounting/` (inherits the middleware backoffice role gate; views also
`@login_required`). No Django admin registration beyond the other apps' convention.

##### LedgerAccount — ERPNext Account

| Field | Type | ERPNext field | Notes |
|---|---|---|---|
| `name` | CharField(200) unique | account_name (as key) | account name is the key, as in ERPNext |
| `parent` | FK self, PROTECT, null=True, related_name="children" | parent_account | null = root; ERPNext roots have no parent either (top of tree) |
| `is_group` | BooleanField default False | is_group | |
| `root_type` | CharField choices ASSET/LIABILITY/EQUITY/INCOME/EXPENSE, blank for non-roots | root_type | required on roots, inherited otherwise |
| `report_type` | CharField choices BALANCE_SHEET/PROFIT_AND_LOSS, blank | report_type | inherited from parent |
| `account_type` | CharField choices (trimmed ERPNext list: Cash, Bank, Stock, Receivable, Payable, Income Account, Direct Income, Indirect Income, Expense Account, Direct Expense, Indirect Expense, Cost of Goods Sold, Round Off, Tax, Equity, Temporary, Current Asset, Current Liability, Fixed Asset, Liability, Stock Received But Not Billed, Stock Adjustment) | account_type | full ERPNext list trimmed to restaurant-relevant values |
| `account_number` | CharField(50) blank | account_number | optional manual numbering |
| `freeze_account` | BooleanField default False | freeze_account | blocks new GL entries while set |
| `disabled` | BooleanField default False | disabled | |

Skipped (documented deviations): `company` (single company), `account_currency` +
currency fields (single NGN), `tax_rate` (no tax), `balance_must_be`, `include_in_gross`,
`account_category`, Nested Set `lft/rgt/old_parent` (tree ordering via `parent` FK + name
ordering instead).

Validation (`clean`, ported from `account.py`): parent must be a group; no self-parent; no
cycles; roots require `root_type`; non-roots inherit `root_type`/`report_type` from parent;
a group with children cannot be disabled; an account with children cannot become a leaf.
Deletion: `PROTECT` against `GLEntry`, `JournalEntryAccount`, `PaymentGLMapping`,
`Warehouse.account`, `ItemGroup.*_account`, `Restaurant`/`ProductionUnit` account FKs; `clean`
also blocks deletion of any account referenced by a GL entry (ERPNext behavior).

##### FiscalYear — ERPNext Fiscal Year

| Field | Type | ERPNext field |
|---|---|---|
| `name` | CharField(10) unique | year |
| `year_start_date` | DateField | year_start_date |
| `year_end_date` | DateField | year_end_date |
| `disabled` | BooleanField default False | disabled |
| `is_short_year` | BooleanField default False | is_short_year |

Skipped: `companies` child table (single company), `auto_created`. Validation (`clean`):
`year_end_date > year_start_date` (ERPNext `validate`); enabled years may not overlap (guard
added because ERPNext's per-company overlap check has no port target in a single-company
system). `FiscalYear.get_for(date)` classmethod returns the enabled year covering a date or
raises (ERPNext `get_fiscal_year` behavior).

##### CostCenter — ERPNext Cost Center

| Field | Type | ERPNext field |
|---|---|---|
| `name` | CharField(100) unique | cost_center_name |
| `parent` | FK self, SET_NULL, null=True, blank=True | parent_cost_center |
| `is_group` | BooleanField default False | is_group |
| `disabled` | BooleanField default False | disabled |

Skipped: `company`, `cost_center_number`, Nested Set fields. Validation: same tree rules as
LedgerAccount (parent is group, no cycles, group-with-children cannot be disabled).

##### GLEntry — ERPNext GL Entry

| Field | Type | ERPNext field | Notes |
|---|---|---|---|
| `posting_date` | DateField | posting_date | |
| `account` | FK LedgerAccount, PROTECT | account | leaf accounts only |
| `cost_center` | FK CostCenter, SET_NULL, null=True | cost_center | optional (ERPNext mandatory-CC company setting not ported) |
| `debit` | DecimalField(14,2) default 0 | debit | exactly one of debit/credit non-zero |
| `credit` | DecimalField(14,2) default 0 | credit | |
| `against` | CharField(200) | against | comma-joined balancing account names (simplified from ERPNext party/against) |
| `voucher_type` | CharField(50) | voucher_type | e.g. "Order", "Journal Entry" |
| `voucher_no` | CharField(100) | voucher_no | order `invoice_number` / JE name |
| `remarks` | TextField blank | remarks | |
| `fiscal_year` | FK FiscalYear, PROTECT | fiscal_year | resolved from posting_date |
| `is_cancelled` | BooleanField default False | is_cancelled | flipped by reversals, never un-flipped |
| `is_opening` | BooleanField default False | is_opening | |

Skipped (deviations): `party`/`party_type`, `against_voucher*` dynamic links, all currency +
exchange fields, `project`, `due_date`, `finance_book`, `is_advance`, `to_rename`,
`voucher_detail_no`.

Immutability: `save()` blocks updates on existing rows except the reversal workflow flipping
`is_cancelled` (private flag, same pattern as `Order._allow_cancellation`);
`delete()` raises (ERPNext GL entries are never edited or deleted). Posting-time validation
(service-side, ported from `gl_entry.py validate` + `make_gl_entries`): account is a leaf, not
disabled, not frozen; posting_date within the resolved fiscal year.

##### JournalEntry — ERPNext Journal Entry

| Field | Type | ERPNext field | Notes |
|---|---|---|---|
| `voucher_type` | CharField choices JOURNAL/CASH/BANK/WRITE_OFF/OPENING, default JOURNAL | voucher_type | trimmed from ERPNext's 18 types |
| `posting_date` | DateField | posting_date | |
| `reference_no` | CharField(50) blank | cheque_no | |
| `reference_date` | DateField null=True | cheque_date | |
| `remark` | TextField blank | remark + user_remark | |
| `status` | CharField DRAFT/SUBMITTED/CANCELLED default DRAFT | docstatus | submit/cancel pattern per §6.0 |
| `total_debit` | DecimalField(14,2) default 0, editable=False | total_debit | recomputed on save |
| `total_credit` | DecimalField(14,2) default 0, editable=False | total_credit | |
| `difference` | DecimalField(14,2) default 0, editable=False | difference | must be 0 to submit |
| `write_off_amount` | DecimalField(12,2) default 0 | write_off_amount | informational; required non-zero when voucher_type=WRITE_OFF |
| `is_opening` | BooleanField default False | is_opening | |
| `amended_from` | FK self, SET_NULL, null=True, blank=True | amended_from | amendment chain (#167) |

Skipped: multi-currency, `write_off_based_on`, party fields, inter-company, deferred/periodic
types, `pay_to_recd_from`, `letter_head`.

Methods (mirroring `apps/staff/models.py` submit/cancel style):
- `submit()` atomic: requires DRAFT; validates rows (`set_total_debit_credit` rules — no row
  with both debit and credit, no duplicate account+cost_center rows, `difference == 0`,
  `total_debit > 0`); then creates GLEntries per row with `voucher_type="Journal Entry"`,
  `voucher_no=name`, `remarks=remark or row remarks`, `is_opening`; status → SUBMITTED.
- `cancel()` atomic: requires SUBMITTED; creates mirror negated GLEntries with remarks
  "On cancellation of {name}", marks the originals `is_cancelled=True`; status → CANCELLED.
- `amend()` (ERPNext `Document.amend`): only from CANCELLED; copies the JE (same rows, posting
  date, remark) into a new DRAFT with `amended_from` set.

##### JournalEntryAccount — ERPNext Journal Entry Account (child rows)

| Field | Type | ERPNext field |
|---|---|---|
| `journal_entry` | FK JournalEntry, CASCADE, related_name="accounts" | parent |
| `account` | FK LedgerAccount, PROTECT | account |
| `cost_center` | FK CostCenter, SET_NULL, null=True, blank=True | cost_center |
| `debit` | DecimalField(14,2) default 0 | debit_in_account_currency (single-currency collapse) |
| `credit` | DecimalField(14,2) default 0 | credit |
| `remarks` | CharField(200) blank | user_remark |

#### 6.8.4 Model changes outside accounting

- **`payments.PaymentGLMapping.default_account`** CharField(200) → FK `LedgerAccount`,
  PROTECT. `clean()` requires the mapped account to be a leaf and not disabled. Data migration
  (separate file, per migration rules): match each existing string to an account by name
  (case-insensitive); if missing, create a leaf account with that name — parent "Assets" root
  (created if needed), `root_type=ASSET`, `account_type=Cash` for `mode.type=CASH` else `Bank`.
  Runtime call sites updated: `apps/orders/services.py:927-939` (settlement requires the FK
  mapping) and `apps/orders/views_pos.py:97-104` (settle dialog filters
  `gl_mapping__isnull=False` only).
- **`settings.Restaurant`** (merged Company + POSProfile surface) gains nullable account FKs:
  `default_income_account`, `default_expense_account` (Company defaults),
  `round_off_account` (Company `round_off_account`), `account_for_change_amount`,
  `write_off_account`, `write_off_cost_center` (ex-POSProfile), `cost_center` FK CostCenter
  (POSProfile `cost_center`). All optional in the model; settlement enforces the ones it needs.
  Settings form gains an "Accounting" section.
- **`settings.ProductionUnit.income_account`** FK LedgerAccount, null=True — the departmental
  split hook (Kitchen = FOOD income, Bar = DRINKS income). *(Addition beyond ERPNext — the
  food/drinks departmental split is core; see AGENTS.md departmental split.)*
- **`inventory.ItemGroup`** gains `income_account` / `expense_account` FKs, null=True —
  ERPNext Item Group fields, ported.
- **`inventory.Warehouse.account`** FK LedgerAccount, null=True — ERPNext Warehouse stock
  account; credited with the COGS-side stock value at settle for stock items.
- **`apps/orders/management/commands/seed_pos_setup.py`** must seed accounts before creating
  `PaymentGLMapping` rows (strings would now violate the FK).

#### 6.8.5 Posting rules — order settle (translated from ERPNext GL composer)

`accounting.services.post_order_gl(order)` runs inside `settle_order`'s atomic block, after the
order flips SUBMITTED and the "POS Order" stock deductions are written. All entries get
`voucher_type="Order"`, `voucher_no=order.invoice_number`,
`posting_date=order.posting_date`, `fiscal_year=FiscalYear.get_for(posting_date)` (raises if
no enabled year covers it), `cost_center=Restaurant.cost_center` (when set).

| # | Dr | Cr | Amount | Account resolution |
|---|---|---|---|---|
| 1 | — | income account | Σ item amounts per account | per item: `item.item_group.income_account` → `ProductionUnit.income_account` (by item department) → `restaurant.default_income_account` (required — settle raises if resolution ends empty) |
| 2 | payment account | — | per OrderPayment: `amount`, reduced by `order.change_amount` on the first row whose account equals `restaurant.account_for_change_amount` (ERPNext default change handling) | `payment.mode_of_payment.gl_mapping.default_account` (required) |
| 3 | — | `restaurant.round_off_account` | `rounding_adjustment` (credit may be negative for round-down) | required when `rounding_adjustment != 0` |
| 4 | expense account (COGS) | `order.stock_warehouse.account` | FIFO outgoing value of the settle-time "POS Order" SLEs, aggregated per account | expense: `item.item_group.expense_account` → `restaurant.default_expense_account` (required when stock items exist) |

`against` = comma-joined names of the balancing accounts per entry. Entries with the same
account/against/fiscal-year/cost-center merge (ERPNext `merge_similar_entries` convention).
Returns (`order.is_return`) skip GL entirely (§6.8.2.6). Tax legs absent (§6.8.2.3).

**Order cancel:** `accounting.services.reverse_order_gl(order)` inside `cancel_order`'s atomic
block — mirror negated entries with remarks "On cancellation of {invoice_number}", originals
`is_cancelled=True` (ERPNext `make_reverse_gl_entries`). Balance is guaranteed because the
mirror exactly negates the original set.

#### 6.8.6 HTMX frontend

All pages extend the standard backoffice base; nav gains an **Accounting** section in
`templates/web/app/app_base.html` (Chart of Accounts, Journal Entries, GL Entries, Fiscal
Years, Cost Centers).

- **Chart of accounts** (`accounting:account_list`): tree page, groups rendered with
  indentation and expand/collapse via HTMX partial refresh; create/edit form
  (`accounting:account_form`); disable/freeze actions; delete blocked server-side.
- **Journal entries** (`accounting:journal_entry_list` / `_form` / `_submit` / `_cancel` /
  `_amend`): status-filtered list; form with dynamic account rows using the existing
  `add_formset_row` / `remove_formset_row` formset pattern
  (`apps/inventory/views.py:23-24, 349-410`); totals bar updates via Alpine; submit/cancel/
  amend as HTMX POST buttons per row with SweetAlert confirm.
- **GL entries** (`accounting:gl_entry_list`): read-only table, filters on account, voucher,
  date range, cost center; `is_cancelled` badge; sorted by posting_date/id.
- **Fiscal years / cost centers**: simple list + form CRUD following the payments
  master-data pages.
- **Settings**: Restaurant form gains the Accounting section (7 account/cost-center FKs).

#### 6.8.7 Seed and migrations

- `payments/migrations/00XX_paymentglmapping_default_account_fk.py` — schema change generated
  by `makemigrations`; separate data migration matches strings to accounts and creates missing
  ones (see §6.8.4).
- `apps/accounting/management/commands/seed_chart_of_accounts.py` — idempotent chart seed:
  Assets (group) → Cash Account (Cash) + Bank Accounts (group) → Electronic Account (Bank);
  Inventory (group) → stock-in-hand leaves for each warehouse; Income (group) → Food Sales +
  Drinks Sales; Expenses (group) → Cost of Goods Sold + Round Off; Equity (group) → Owner's
  Equity. Creates CostCenters (Kitchen, Bar), current-year FiscalYear, links
  `ProductionUnit.income_account` (Kitchen→Food Sales, Bar→Drinks Sales), `Warehouse.account`
  leaves, `Restaurant` defaults, and refreshes `PaymentGLMapping` mappings.
- `seed_pos_setup` updated to invoke the chart seed first.

#### 6.8.8 Tests (`apps/accounting/tests/`)

- `test_models.py` — account tree rules (parent-is-group, no cycle/self-parent, root_type
  inheritance, disable/leaf guards, deletion protection), fiscal year (end > start, overlap,
  `get_for`), cost center tree, GL entry immutability.
- `test_journal_entry.py` — submit posts balanced GL (ΣDr = ΣCr per account), unbalanced /
  both-debit-and-credit-row / duplicate-row rejections, frozen/disabled/group accounts
  rejected, cancel reverses with `is_cancelled` + negated mirrors, amend copies CANCELLED →
  DRAFT with `amended_from`, write-off voucher requires `write_off_amount`.
- `test_order_gl.py` — settle posts payment/income/COGS/round-off legs (departmental income
  split across two ProductionUnits, change reduction on cash leg, rounding), cancel reverses,
  return orders skip GL, missing account config raises, fiscal-year guard raises.
- `test_payment_gl_mapping.py` — FK required + leaf-only validation (extends the existing
  payments test file).
- `test_views.py` — backoffice gate, CRUD, submit/cancel/amend flows.
- Existing orders/staff test suites gain a shared accounting setup helper
  (`apps/accounting/tests/utils.py` — test-only) because settle now requires the account chain.

#### 6.8.9 Docs to update (same task)

`docs/architecture/apps.md`, `dependencies.md`, `data-model.md`, `state-machines.md`
(JournalEntry states), `docs/workflows/orders.md` + `payments.md` (GL legs, FK mapping),
`docs/execution-flows/submit-order.md` + `payment.md` (GL side effects), new
`docs/workflows/accounting.md` + index entry in `docs/README.md`.

#### 6.8.10 Deviations from reference

1. Single-tier posting (no consolidated Sales Invoices at close) — §6.8.2.1.
2. No party ledger / receivable legs — §6.8.2.2.
3. No tax accounts or tax GL — §6.8.2.3.
4. Inventory-document GL deferred to Phase 7 — §6.8.2.5.
5. Return-order GL deferred to Phase 6 — §6.8.2.6.
6. Flat FK tree instead of Nested Set for Account/CostCenter — §6.8.3.
7. Single-currency collapse of all `*_in_account_currency` / exchange fields — §6.8.3.
8. `against` holds balancing account names instead of party names — §6.8.5.
9. `ProductionUnit.income_account` departmental resolution — §6.8.4 (addition).
10. Enabled-fiscal-year overlap guard — §6.8.3 (addition).

---

### 6.9 Daily P&L (Phase 7)

**Status:** not started — detailed plan to be written after accounting is complete.

**FEATURES.md sections:** A14, C (departmental P&L)
**Dependencies:** accounting (GL/COGS), inventory (Kitchen consumption), orders (sales)
**Key models:** DailyP&L, P&LLineItem, P&LAmendment
**Reference doctypes to consult:** URY Daily P&L, URY P&L doctypes (materials, COGS, expenses)

---

### 6.10 Reports (Phase 8)

**Status:** not started — detailed plan to be written after P&L is complete.

**FEATURES.md sections:** A15, C (departmental daily reports)
**Dependencies:** all apps
**Key models:** query-based (no persistent aggregates unless needed)
**Reference doctypes to consult:** ERPNext Sales Invoice reports, Stock Ledger reports

---

### 6.11 Refunds Completion (Phase 6)

**Status:** not started — detailed plan to be written with the Phase 6 (accounting) work; remaining scope: refund GL reversal postings, wastage posting, partial returns.

**FEATURES.md sections:** A18
**Dependencies:** orders, payments, inventory, accounting (GL reversal)
**Key models:** RefundEntry, RefundPaymentEntry, RefundStockEntry (may be part of orders app)
**Reference doctypes to consult:** ERPNext Payment Entry (reversal), Stock Ledger Entry (positive)

---

### 6.12 Printing App (Phase 9)

**Status:** not started — detailed plan to be written last, after the accounting/reporting phases. (A stub
`apps/orders/printing.py` exists; `KOT.print_status` / ticket reprint flow are wired.)

**FEATURES.md sections:** A8
**Dependencies:** orders (ticket data to print)
**Key models:** PrintJob, PrinterConfig (extracted from `ProductionUnit.printer_*` fields)
**Reference doctypes to consult:** URY Printer Settings, Network Printer Settings, URY print hooks

---

### 6.13 Deferred features: Customer Management & Coupon Engine

Neither is part of the core phases (8–12); detailed plans are written when each is
picked up later.

**Customer Management** — FEATURES.md A11; depends on orders (link orders to a `Customer`
instead of a bare `customer_name` string).
- Key models: Customer, CustomerGroup, credit limits
- Reference doctypes: ERPNext Customer, Customer Group, Customer Credit Limit

**Coupon Engine** — FEATURES.md A13 #130–131 (pricing rules, coupon codes), A10 #98–99
(cashier % discount); depends on orders, payments.
- Key models: CouponCode, pricing rule
- Reference doctypes: ERPNext Coupon Code, Pricing Rule

---
### 6.14–6.23 Completed decisions & refactors (archived)

Implemented. Verbatim copies in `docs/archive/PLAN-history.md`; current facts distilled in
§4 App Summaries and AGENTS.md.

| § | Title | What it decided / changed |
|---|---|---|
| 6.14 | Single-Location Settings Cleanup | Branch/POSProfile/TaxTemplate removed; settings merged into the `Restaurant` singleton; `ModeOfPayment.enabled` + exactly-one `is_default` |
| 6.15 | Order Numbering — Continuous Sequence | every new order number = last + 1, forever, via `OrderSequence` |
| 6.16 | POS Template Fragmentation | `pos/index.html` split into `partials/{gates,cart,catalog,payment}/` |
| 6.17 | Send to Kitchen & Bar — Ticket Print State + POS Cancellation | sent draft is immutable; cancel-and-replace (no KOT diffing); `KOT.print_status` |
| 6.18 | Orders Backoffice Control Room | query-based orders dashboard, order register, kitchen/bar ticket register |
| 6.19 | Orders POS Review Decisions | optional receipt print, settlement validation, 50-open-draft limit |
| 6.20 | Inventory and POS Stock Rules | FOOD lines bypass POS stock; DRINKS reserve/deduct from the Bar warehouse; receipts post to Store; Store→department transfers; reconciliation reasons |
| 6.21 | POS Workbench Redesign | three-column layout, catalogue search, add-on dialog |
| 6.22 | POS Shell Navigation | wordmark + cashier dropdown, full-width footer nav |
| 6.23 | Paid-Order Ticket Guarantee | settle auto-creates departmental tickets when none exist |

---
### 6.24 Order Stage Exits — Delete, Cancel, Settle-Print, Return (deviation)

**Status:** implemented 2026-08-17 — delete-for-unsent drafts (POS + backoffice), cancel-only-with-KOT, settle sets `invoice_printed*` with non-blocking receipt print, `submit_return` (stock restore + negative refund rows + drawer effect), `OrderPayment` negative-on-return change, migration `0024`. GL reversal, wastage, and partial returns remain in Phase 11.

**Client decision:** the order lifecycle gets exactly one exit per stage, grounded in the
mainstream restaurant-POS stage model (Toast, Square for Restaurants, Lightspeed, Oracle
Simphony) rather than the ERPNext/URY document model:

1. **Draft, nothing sent** (no KOT, no receipt) — **delete** freely. No reason, no manager
   PIN. Nothing operational happened yet; the anti-fraud control at this stage is shift-close
   drawer reconciliation and per-cashier reports, not deletion ceremony. ("Cashier pockets
   money and deletes the draft" is a missing payment record, which shows up at shift close
   whether the draft is deleted or kept.)
2. **Sent to kitchen/bar** (KOT exists) — **cancel only**, never delete. Cancel requires a
   reason, prints cancellation tickets to the kitchen (so food is not cooked), and lands on
   the per-cashier cancel report. The receipt print is explicitly **not** a lock: the KOT is
   the point of no return.
3. **Paid (submitted)** — **return only**, never cancel. A return is a separate negative
   document (already built as `is_return` + `return_against` in Phase 5). Submitting the
   return restores stock for stock-tracked drinks, records negative refund payment rows
   mirroring the source payment methods, and reduces the shift-close expected drawer.
4. **Receipt** — printed automatically at settlement (non-blocking; a printer failure never
   stops a sale), reprintable any time from order history. No pre-payment receipt print
   exists, so "receipt printed" implies "paid" and needs no lock of its own.

**References consulted:**

- Toast / Square / Lightspeed / Oracle Simphony (public POS documentation and behaviour):
  open check → sent → closed stages; voids print a kitchen chit and require a reason;
  closed checks are refunded to the original payment method, never voided; receipts print
  on payment confirmation, and printer failure never blocks the payment.
- ERPNext `pos_invoice.py` `before_cancel` — paid POS invoices inside a submitted closing
  entry cannot be cancelled (return is the only path); `controllers/status_updater.py`
  — status "Return" is a *submitted document* (`is_return == 1 and docstatus == 1`),
  distinct from "Cancelled" (`docstatus == 2`).
- URY `pos/src/data/order-types.ts` — "Return" is a first-class order-list status;
  `ury/ury_pos/api.py` + `button_permission.py` — URY has no bespoke cancel/return logic,
  it delegates to standard ERPNext document actions gated by role permissions.
- RestPOS current code (verified 2026-08-16): `Order.delete()` guards, `_ensure_editable()`
  (`invoice_printed` lock), `cancel_sent_order()` (`invoice_printed or kots` eligibility),
  `discard_order()` (empty drafts only — a draft with items and no KOT is currently
  **stuck**), `claim_receipt_print()`/`pos_order_print` (pre-payment receipt on drafts),
  `settle_order()` (no receipt logic), `make_return()` (paid-only, creates return draft,
  no submit path), `collect_submitted_payment_totals()` (excludes returns), and the
  `order_detail.html:25` precedence bug that offers "Cancel order" to return drafts.

**Why a deviation:** ERPNext cancels submitted-unpaid invoices and URY mandates printing a
receipt before submission — both artifacts of an accounting-first document model. RestPOS
settlement requires full payment, so a submitted-unpaid state does not exist; receipts move
to post-payment (the universal POS pattern); and the reference's document-centric cancel vs
return split is replaced with stage-bound exits. The deviation is documented here per the
AGENTS.md protocol.

#### Business logic

**1. Delete for unsent drafts**

- New `pos_order_delete` view + URL `order/<int:pk>/delete/` + cart button "Delete order"
  shown when `not order_sent` (and the order is not settled). POST redirects to `pos_home`
  (no HTMX partial — the cart ceases to exist).
- `Order.delete()` already guards: DRAFT only, no KOTs, not `invoice_printed`, releases
  drink reservations. **New requirement:** it must also purge the order's audit events —
  `OrderAuditEvent.order` is `PROTECT` and events refuse instance deletion, so delete must
  issue a queryset `.delete()` on `audit_events` (bypasses the instance guard deliberately;
  one-line comment explaining why). Deletion of an unsent draft carries no audit-event
  value; the CREATED/ITEM_ADDED events describe a draft that never became operational.
- `discard_order()` / `pos_order_discard`: superseded by delete for every unsent draft.
  Remove the POS discard path (view, URL, template button, service if unreferenced). The
  `DISCARDED` status stays in the model and status choices for legacy rows.

**2. Cancel only for sent orders**

- `cancel_sent_order()`: eligibility becomes `not locked.kots.exists()` only — drop the
  `invoice_printed` branch (post-settlement orders are blocked by the status check anyway).
- Backoffice `order_cancel()`: reject DRAFT orders without KOTs
  ("This order was never sent — delete it instead of cancelling."). The SUBMITTED-unpaid
  branch stays as defence-in-depth (unreachable while settlement requires full payment).
- `_ensure_editable()`: remove the `invoice_printed` lock — KOT existence is the only
  draft lock. Remove the now-dead `invoice_printed` checks in `pos_order_add_item` and
  `pos_order_clear`, in `Order.save()`'s draft-field guard, and in
  `OrderItem.save()`/`delete()`. Keep the "printed receipt cannot be marked unprinted"
  guard.
- Templates: replace every `order_sent or order.invoice_printed` condition with
  `order_sent` (guests.html lock badge/stepper, items.html edit buttons, totals.html
  cancel section). `open_draft_orders()` "draft" filter drops `invoice_printed=False`.

**3. Receipt prints at settlement, reprint from history**

- Remove the cart Print/Reprint button (totals.html), `pos_order_print` view + URL, and
  `claim_receipt_print()` (dead once drafts never print).
- `settle_order()` sets `invoice_printed=True`, `invoice_printed_at`, `invoice_printed_by`
  on the existing guarded save — settlement *is* the receipt event.
- `pos_order_settle()` (view) calls `printing.print_receipt(order)` after
  `services.settle_order()` returns; on failure it shows a warning ("Order settled, but the
  receipt failed to print — reprint it from order history") and the sale stands. Never
  blocks settlement.
- Reprint stays as-is: `pos_order_history_print` (SUBMITTED orders, history detail).
- Remove the now-dead cart receipt banners (`receipt_print_error` context handling).

**4. Return only for paid orders**

- Creation is already gated (`make_return` requires SUBMITTED + `is_paid`). Fix
  `order_detail.html` so return drafts never get the generic "Cancel order" button
  (the `or/and` precedence bug) — use nested `{% if %}` blocks.
- New `submit_return(order, actor)` service:
  - Locked DRAFT + `is_return` + `return_against` SUBMITTED; re-validate each line's
    `return_against_item` reference against the source order.
  - Restore stock: positive SLEs for stock-tracked drink lines
    (`voucher_type="POS Return"` — parameterise `_restore_stock()`'s voucher type), using
    the order's `stock_warehouse` snapshot copied at `make_return` time.
  - Refund rows: mirror each source payment as a negative `OrderPayment`
    (`amount=-source.amount`, `reference_no=""` — the unique constraint on
    (mode, reference) must not collide with the original, and a refund is not the same
    card reference). Requires the `OrderPayment` change below.
  - `paid_amount` = negative refund total, `is_paid` stays False, `status=SUBMITTED` via
    `_transition("_allow_submit")`, `submitted_at`, audit `RETURN_SUBMITTED`
    (metadata: source order). Returns are immutable documents, not "paid sales" — revenue
    queries filter `is_paid=True` and already exclude returns.
- New backoffice `order_return_submit` view + URL + "Submit return" button (manager-only,
  mirroring `order_return`'s guard) on DRAFT return orders.
- Abandoning a return draft = deleting it (stage rule 1): a manager-only "Delete draft"
  button on `order_detail.html` for any DRAFT order (return or not) posting to a new
  backoffice `order_delete` view; `Order.delete()` guards apply.
- Drawer effect: `expected_closing_amounts()` (staff/services.py) must subtract refunds.
  Aggregate negative payment sums of SUBMITTED return orders submitted inside the shift
  window (`status=SUBMITTED, is_return=True, submitted_at in period`) and add them to
  `collect_submitted_payment_totals()` results per mode.

**Model/migration change (OrderPayment):**

- Drop the `orders_payment_amount_gt_zero` CheckConstraint via `makemigrations` (negative
  refund rows are now valid on return orders).
- `OrderPayment.save()`: allow `amount < 0` only when `order.is_return` (and order DRAFT —
  the row is created inside `submit_return` before the guarded transition); normal orders
  keep "greater than zero".

#### Tests

| File | Test | Asserts |
|---|---|---|
| apps/orders/tests/test_pos_views.py | `test_delete_unsent_draft` | POST delete removes the draft + items + audit events; redirect to pos_home |
| | `test_delete_sent_draft_blocked` | KOT'd draft delete → ValidationError, order remains |
| | `test_cancel_requires_kots` | `cancel_sent_order` on unsent draft raises; cart shows no Cancel button when `not order_sent` |
| | `test_settle_marks_receipt_printed` | settle sets `invoice_printed*`; `print_receipt` called after settlement (patched), failure → warning + still settled |
| | `test_no_print_button_in_cart` | totals.html has no print form for drafts |
| apps/orders/tests/test_order.py | `test_submit_return_restores_drink_stock` | SLE with positive qty, voucher "POS Return"; bin/stock correct |
| | `test_submit_return_creates_negative_refund_rows` | refund rows mirror source modes with negative amounts; `paid_amount` negative; status SUBMITTED; `RETURN_SUBMITTED` audit |
| | `test_submit_return_requires_paid_source` | non-draft / non-return / unpaid source rejected |
| | `test_negative_payment_only_on_returns` | OrderPayment.save() rejects negative on normal orders |
| apps/orders/tests/test_backoffice_views.py | `test_return_draft_shows_submit_not_cancel` | return draft detail has Submit return + Delete, no Cancel order |
| | `test_order_delete_backoffice` | manager deletes DRAFT; cashier blocked |
| apps/staff/tests/ | `test_expected_closing_amounts_net_of_refunds` | submitted return's refund rows reduce expected drawer per mode |

Existing tests to update: anything asserting the `invoice_printed` draft lock, `pos_order_print`,
`claim_receipt_print`, `discard_order` POS path, or the discard button.

#### Documentation (same task)

- `docs/workflows/orders.md` — rewrite Cancellation/Discard/Return and Submission sections:
  stage exits, settle-prints receipt, `submit_return`, no pre-payment printing.
- `docs/architecture/state-machines.md` — Order state diagram gains RETURN draft submit and
  delete-for-unsent; `invoice_printed` no longer a draft lock.
- `docs/execution-flows/print-receipt.md` — now: auto-print at settle, reprint from history.
- `docs/execution-flows/submit-order.md` — add receipt print step and the refund exclusion.
- `docs/architecture/side-effects.md` — settlement gains receipt print + `invoice_printed`
  write; return submission gains SLE restore + negative payment rows + drawer effect.
- Plan.md §3 table: built with the phase merge — the orders (Phase 5) row gained "stage exits
  §6.24", and refunds completion folded into accounting (Phase 6) with its remaining scope
  (GL reversal postings, wastage, partial returns).

---

### 6.25 Opening Balances and Go-Live Setup (Phase 6)

**Status:** planned — detailed plan below; not implemented.

**Source:** `docs/accounting-scope-recommendations.md` §3 (approved 2026-08-16).

A single reviewed opening Journal Entry using Phase 6's
`is_opening` / `OPENING` voucher type. One selected opening date, a balanced entry, a source or
note per balance, protection against accidental duplicate opening sets, and a review + submit
action before the opening becomes effective. No import wizard and no journal-import screen.
This is a **go-live prerequisite** if RestPOS is the accounting source of truth.

**Dependencies:** accounting (Phase 6 JournalEntry OPENING workflow), settings (Restaurant)
**Key models:** none new — reuses `JournalEntry` (`is_opening`) +
`JournalEntryAccount`; an opening-balance review/submit service
**Reference files:** `docs/accounting-scope-recommendations.md` §3; ERPNext Company
opening-balance setup, Journal Entry (`is_opening`)

---

### 6.26 Trial Balance and Financial Statements (Phase 8)

**Status:** planned — detailed plan below; not implemented.

**Source:** `docs/accounting-scope-recommendations.md` §4 (approved 2026-08-16).

Read-only General Ledger report, Trial Balance, and a simple Profit &
Loss report over `GLEntry`, grouped by account, fiscal year, posting date, and cost center.
Drill-down to the source voucher and its GL entries; cancelled entries and their reversals
handled consistently. No balance sheet and no formal statements.

**Dependencies:** accounting (Phase 6 GL posting), reports (Phase 8 report surface)
**Key models:** query-based (no persistent aggregates)
**Reference files:** `docs/accounting-scope-recommendations.md` §4; ERPNext Trial Balance /
Profit & Loss reports, GL Entry

---

### 6.27 Cash Shortage and Excess Posting (Phase 6)

**Status:** planned — detailed plan below; not implemented.

**Source:** `docs/accounting-scope-recommendations.md` §1 (approved 2026-08-16).

Configurable ledger accounts for Cash Shortage Expense and Cash Over /
Short Income (or one sign-aware account). When a submitted shift close has a non-zero approved
variance, a Journal Entry or dedicated shift-variance posting linked to the closing entry is
created atomically with the approved close, immutable after posting, and reversed if the
closing entry is cancelled. Material variances require manager approval or a required
explanation.

**Dependencies:** accounting (Phase 6 GL posting), staff (shift close `POSClosingEntry`),
payments
**Key models:** shift-variance posting (GLEntry or a dedicated variance document tied to
`POSClosingEntry`), Cash Shortage Expense / Cash Over Income `LedgerAccount`s,
`Restaurant` variance-account configuration
**Reference files:** `docs/accounting-scope-recommendations.md` §1; ERPNext GL Entry, Payment
Entry, POS Closing Entry

---

### 6.28 Supplier Payables and Supplier Invoices (Phase 2)

**Status:** planned — detailed plan below; not implemented.

**Source:** `docs/accounting-scope-recommendations.md` §6 (approved 2026-08-16).

A Supplier master separate from the `supplier_name` string on
`PurchaseReceipt`; supplier invoice / purchase-bill documents with lines linked to received
stock or expenses; accounts-payable balances; supplier payment entries; payment-to-invoice
allocation; and cancellation/reversal rules. Purchases record Dr Stock-in-Hand / Cr Accounts
Payable on the invoice and Dr Accounts Payable / Cr Bank (or Cash) on payment.

**Dependencies:** inventory (Phase 2 PurchaseReceipt, Phase 7 inventory-document GL — §6.8.2.5),
accounting (Phase 6 GL)
**Key models:** Supplier, SupplierInvoice, SupplierInvoiceItem, SupplierPayment,
payment-allocation rows
**Reference files:** `docs/accounting-scope-recommendations.md` §6; ERPNext Supplier, Supplier
Group, Purchase Invoice, Payment Entry (payment allocation), AP reports

# RestPOS — Feature Specification

This document specifies what the system does, organised by back office, POS frontend, and
cross-cutting areas. **Planned** features (section E) are specified but not yet implemented.
**Deferred** features (section F) are intentionally out of scope until further notice.
Implementation status lives in `PLAN.md`.

## Scope

- **Single location.** One restaurant, one settings surface (`Restaurant` singleton). No
  branches, no multi-site configuration.
- **Cashier-operated POS.** Cashiers take orders and payments on the POS screen. Roles: Admin,
  Manager, Cashier. Waiters have no system access.
- **No tables or floor plans.** Orders start by type (Dine-In / Take-Away) and guest count.
- **No tax system.** Totals come from item lines plus whole-naira rounding.
- **No discounts or coupons.** There is no open discount path.
- **Departmental split.** Every item is FOOD or DRINKS. Tickets route by department; revenue is
  tracked per department per order line.
- **Operational stock, not recipes.** No BOM or ingredient-level consumption. POS stock
  reservation and deduction apply to drinks only; food usage is counted through kitchen
  consumption reconciliations.
- **Local network only.** Django runs on the cashier desktop; the back office is reachable from
  any device on the same WiFi. No internet dependency.

## A. Back Office

### A1. Settings & Configuration

| # | Feature | What it does |
|---|---|---|
| 1 | Restaurant settings | The singleton configuration record. Holds company name, invoice prefix, address, active menu, the default (bar/POS) warehouse, the central store warehouse, the maximum number of open draft orders, and whether cashiers can browse full order history. Every other area of the system references it. |
| 2 | Production units | One production unit per department: the Kitchen (FOOD) and the Bar (DRINKS). Each unit owns its department's warehouse, printer configuration (IP address, paper width, cut mode), and a flag to suppress ticket printing for takeaway orders. |
| 3 | Staff roles | Three roles: Admin (everything, including Django admin), Manager (back office + POS), Cashier (POS only). Only admins assign roles. |

### A2. Menu Management

| # | Feature | What it does |
|---|---|---|
| 4 | Menu | A single named menu bound to the restaurant. Disabling the menu hides all its items from the POS without deleting anything. |
| 5 | Menu items | Links an inventory Item to the menu with its selling rate, special-dish flag, disable flag, and image. The menu item rate is the price the customer pays. |
| 6 | Special dishes | Items flagged special appear under a dedicated filter on the POS for fast access to featured dishes. |
| 7 | Item disable | A disabled menu item disappears from the POS immediately but keeps its pricing in the database. |
| 8 | Item images | Each menu item can carry an image; the POS shows it on the menu card and falls back to an initials placeholder. |
| 9 | Item variants | A template item (e.g. "Chicken") can have variant items (Quarter, Half, Full), each with its own price. Variants are managed in the back office; POS variant selection is not yet implemented. |
| 10 | Item add-ons | Optional extras on a menu item (e.g. "Extra Cheese"). Selected add-ons join the cart as separate lines at their own prices. |

### A3. Inventory & Stock

| # | Feature | What it does |
|---|---|---|
| 11 | Item master | The product database. Each item records its name, group, unit, department (FOOD/DRINKS), image, and independent flags: sellable, stock-tracked, purchasable. Department or menu membership does not imply stock tracking or purchase eligibility. |
| 12 | Item groups | Flat product categories used for POS filtering and report grouping. |
| 13 | Warehouses | Flat physical locations: the central Store, the Bar (the POS deduction warehouse), and the Kitchen. Meaning comes from configuration, not a role field. |
| 14 | Stock ledger entries | Immutable signed records of every stock movement under Perpetual Weighted-Average Cost (PWAC): quantity (signed), unit rate (inbound: actual rate; outbound: current WAC), value change, and variance (cancellation WAC drift or sale-return). Bin holds the current WAC; ledger is append-only audit. Cancellation posts reversals via `reversal_of_sle`, never edits; posting date is informational, valuation always at current WAC. |
| 15 | Stock entries | Manual movements: Material Receipt (into the Store, at actual rate — market purchase posts Dr SIH / Cr expense, no GRNI) and Material Transfer (Store → Kitchen or Bar) only. Transfers value at the source WAC and dest recalculates its WAC; cannot drive source stock negative. Cancellation reverses at dest current WAC, net zero. |
| 16 | Stock reconciliation | The one-sided adjustment workflow for physical counts, kitchen consumption, waste/damage, and corrections, valued at current WAC. Opening stock (or a first receipt into an empty bin) requires an entered rate to seed WAC. Every reconciliation requires a reason. Consumption adjustments are restricted to the Kitchen warehouse and FOOD items. Waste posts Dr wastage / Cr warehouse. |
| 17 | Purchase receipts | Supplier goods received into the Store: posts Dr SIH (warehouse asset) / Cr GRNI at receipt rate, blending WAC. Supplier is a free-text name with an optional link to the Supplier master. Lines require stock + purchase eligible items. Cancellation blocked if a submitted supplier invoice or allocated payment exists; allowed cancellation reverses at current WAC with drift to the inventory price variance account. |
| 18 | Bins | Per item + warehouse stock position: actual quantity, reserved quantity, and valuation (current WAC). Drives POS drink availability and reservations. |
| 19 | Stock reports | A stock ledger report (movement audit trail) and a stock balance report (opening/received/issued/closing) in the back office. |

### A4. Payment Modes

| # | Feature | What it does |
|---|---|---|
| 20 | Payment modes | Configurable payment types: Cash, Bank, General, Phone. Each can be enabled or disabled; exactly one is the default. |
| 21 | GL account mapping | Each mode maps to a ledger account. Settlement rejects orders paid with a mode that has no mapping. |
| 22 | Change | Only cash modes dispense change. Overpayment on electronic modes is rejected. |

### A5. Shift Management

| # | Feature | What it does |
|---|---|---|
| 23 | POS opening entry | Starts the shift: period, cashier, and an opening float per payment mode. Exactly one shift can be open at a time. |
| 24 | POS closing entry | Ends the shift with a reconciliation per payment mode: opening float, expected amount, cashier-counted amount, and difference. Aggregates the shift's submitted orders. |
| 25 | Shift guards | Closing is blocked while open draft orders exist; a shift with attached orders cannot be cancelled; a closing entry cannot be cancelled once a newer shift is open. |
| 26 | Refund netting | Expected drawer amounts subtract refunds from return orders submitted during the shift and net off cash change. |

### A6. Orders & Tickets

| # | Feature | What it does |
|---|---|---|
| 27 | Order document | The central sale record: invoice number, continuous sequential order number, order type (Dine-In / Take-Away), free-text customer name (default "Walk-in Customer"), guest count, and totals with whole-naira rounding. Statuses: Draft, Submitted, Cancelled, Discarded. |
| 28 | Order lines | Each line stores item, quantity, rate, amount, per-line comments, the customer card index, and department + stock-tracked snapshots. |
| 29 | Order payments | Split payment across modes in one order. Cash overpayment produces change. Electronic payment references must be unique. Payment rows are immutable once the order is settled. |
| 30 | Order lifecycle | One exit per stage: unsent drafts are deleted; sent drafts are cancelled with cancellation tickets; paid orders are refunded through a return order. A configurable cap limits open drafts per shift. |
| 31 | Kitchen & bar tickets | On send, the system creates one ticket per department: FOOD to the kitchen unit, DRINKS to the bar unit. Tickets are snapshots (New Order or Cancelled), numbered KOT-/BOT- (CNCL- for cancellations), with per-ticket print status and retry. Takeaway suppression is per production unit. |
| 32 | Settlement ticket guarantee | Settling an order that never generated tickets creates them automatically, so no paid order escapes the kitchen. |
| 33 | Returns | A manager creates a return draft mirroring the paid order with negative lines. Submitting it restores drink stock, records negative refund payment rows, and reduces shift-close expectations. One active return per order. |
| 34 | Group ordering | The guests stepper raises the guest count; each order line belongs to a customer card (Customer 1, Customer 2, …). Receipts and tickets group lines per customer. Lowering the count below a guest who still has items is blocked. |
| 35 | Audit events | Every order mutation records an immutable event (created, item added, sent, settled, cancelled, returned…) with actor and metadata. |
| 36 | Orders control room | Back-office orders register with status/type/search filters, order detail, ticket register, and a dashboard with today's counts, revenue, and pending tickets. |

### A7. Document Workflow & Integrity

| # | Feature | What it does |
|---|---|---|
| 37 | Submit/cancel immutability | Financial documents follow Draft → Submitted → Cancelled. Submitted records are never edited; corrections post reversal entries. |
| 38 | Deletion protection | Financial records are never cascade-deleted. Orders, payments, and stock ledger entries survive changes to the records they reference. |

### A8. Accounting

| # | Feature | What it does |
|---|---|---|
| 57 | Accounting / GL | Chart of accounts, GL entries, journal entries (incl. opening voucher type), and fiscal years. GL posts at order settlement (income, payment, rounding, COGS at current WAC). Food vs drinks separation uses department, production-unit income accounts, and Daily P&L — not cost centers. |
| 58 | Refunds completion | Refund GL on return submit, wastage posting for non-restockable items, and partial returns. Restockable drinks restore at current WAC; sale-return variance vs original COGS lands in COGS. |
| 59 | Opening balances | A reviewed opening journal entry for go-live, with duplicate protection. |
| 60 | Cash variance posting | Shift-close shortages/excesses post to configurable accounts, atomically with the approved close. |

### A9. Supplier Payables

| # | Feature | What it does |
|---|---|---|
| 61 | Supplier payables | Supplier master, supplier invoices, supplier payments fully allocated to outstanding invoices, and accounts-payable balances per supplier. Invoice creation is receipt-first: the form takes header fields (supplier, dates, bill no., linked purchase receipt, remarks) plus optional expense lines (description + amount). Stock lines are not typed in — on submit they are generated from the linked receipt (qty/rate copied, read-only, rate-locked). Expense-only invoices need no receipt. Stock invoices post Dr GRNI / Cr payable at the receipt rate; expense lines post Dr `Restaurant.default_supplier_expense_account` / Cr payable (missing config is a hard error). Purchase receipts post Dr SIH / Cr GRNI; market purchases via Stock Entry post Dr SIH / Cr expense (no GRNI, no invoice). Payments post Dr payable / Cr cash-bank; cancellation reverses. Receipt cancel is blocked while a submitted invoice or allocated payment exists. |

### A10. Daily P&L

| # | Feature | What it does |
|---|---|---|
| 62 | Daily P&L | A daily profit & loss document (management snapshot, no GL posting): gross sales → COGS (drinks at current WAC) → direct expenses (electricity, materials, ad-hoc) → gross profit → indirect expenses (rent, salaries, depreciation, cash variance) → net profit. Kitchen consumption (reconciliation at current WAC) is shown beside FOOD sales as a memo, not in GP. Sale-return variance posts to COGS (current WAC vs original). Prime cost (drink COGS + labor) is a highlight. Three columns FOOD / DRINKS / TOTAL, amendments, configurable business-day start hour. |

## B. POS Frontend

| # | Feature | What it does |
|---|---|---|
| 39 | Login & routing | Cashier logs in with username/password (show/hide toggle); the session persists until logout or timeout. Users land on POS or back office per role. |
| 40 | Shift gate | The POS refuses to serve orders until a shift is open and shows the open-shift form inline. |
| 41 | Draft orders home | Lists the shift's open drafts in Draft/Sent tabs with item previews and the draft cap; orders resume from here. |
| 42 | Menu catalog | Responsive grid of menu cards (image/initials, name, price) with category sidebar, special filter, and live search. Single click adds to the cart; the product dialog handles quantity, per-line comments, and add-ons. |
| 43 | Drink availability | Stock-unavailable drinks stay visible but greyed and unselectable; food items never use stock availability. |
| 44 | Cart | Order type selector, guests stepper with customer cards, per-line quantity/edit/remove, clear (unsent only), and a live grand total. |
| 45 | Payment dialog | Payment mode inputs (auto-filled with the balance), split payment totals, change display, and settlement validation (full payment, enabled modes, GL mappings). |
| 46 | Order history | Paginated list with filters (status, payment method, order type, search), a detail drawer, receipt reprint for paid orders, and ticket reprint/retry (manager). |
| 47 | Shift close | Preview of the reconciliation before writing anything, then per-mode counted amounts and the difference report. |
| 48 | Shell & feedback | Footer navigation, order breadcrumb, toast notifications, confirmation dialogs for destructive actions, and responsive layout. |

## C. Departmental Split

| # | Feature | What it does |
|---|---|---|
| 49 | Department classification | Every item must be FOOD or DRINKS. Department drives ticket routing, drink stock validation, and per-line revenue tracking. |
| 50 | Revenue split | Each order line snapshots its department, so food and drinks revenue can be summed independently of the single paid total. Separate income accounts per department resolve item group → production unit → restaurant default. |
| 51 | Departmental reports | Food and drinks revenue reported separately, including the daily P&L split (FOOD / DRINKS / TOTAL columns). |

## D. Architecture Constraints

| # | Feature | What it does |
|---|---|---|
| 52 | Local network only | Everything runs on the cashier desktop and the local WiFi. No internet dependency. |
| 53 | Web stack | Django templates + HTMX + Tailwind CSS + Alpine.js. No React, Vue, DRF, or Socket.io. |
| 54 | PostgreSQL | The only supported database. |
| 55 | Exact money | All monetary values use DecimalField. |
| 56 | Printers | Three thermal printers — cashier (USB), kitchen (LAN), bar (LAN) — driven by a local print agent (Planned). |

## E. Planned (not yet implemented)

| # | Feature | What it will do |
|---|---|---|
| 63 | Reports | Sales reports (today, daywise, monthwise, item, employee, service, time), cancelled invoices, average bill value, POS register, trial balance, and a simple P&L. |
| 64 | Printing | The local print agent (localhost HTTP → ESC/POS → printer), receipt and ticket formats, print job routing and status. Printer identity and paper configuration already live on production units. |

## F. Deferred

| # | Feature | What it is |
|---|---|---|
| 65 | Customer management | Customer master, groups, credit limits, and POS customer search/create. Orders keep the free-text customer name until then. |
| 66 | Coupons & pricing rules | Coupon codes, pricing rules, and cashier percentage discounts. |
| 67 | Multi-branch | Separate paid work; the product is single-location. |

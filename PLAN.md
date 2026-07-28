# RestPOS — Implementation Plan

> This document is the implementation plan for RestPOS Phase 1. It has two tiers:
>
> 1. **High-level roadmap (Sections 1–5)** — written once, covers all 8 apps at a strategic
>    level. Read this to understand the full project scope and build sequence.
> 2. **Detailed plans (Section 6)** — written incrementally, one per phase, just before
>    implementation. Each contains model fields, views, templates, tests, and reference files.
>
> **For a new session:** read Sections 1–5, check the status table in Section 3 to find
> where the last session stopped, then read the relevant detailed plan in Section 6.

---

## 1. Project Overview

**RestPOS** is a restaurant POS and management system for a Nigerian restaurant, built with
Django + HTMX + Tailwind CSS + Alpine.js. It covers table management, ordering, kitchen/bar
ticket printing, payments, inventory, daily P&L, and departmental sales split (food vs drinks).

**Phase 1 scope:** local network only. Django runs on the cashier desktop. All operations work
without internet. The owner accesses the back office from any device on the same WiFi.

**Tech stack:**

| Layer | Technology |
|---|---|
| Backend | Django 6.0+ (Python 3.14) |
| Frontend | Django templates + HTMX + Tailwind CSS v4 + Alpine.js + SweetAlerts |
| Database | PostgreSQL |
| Package manager | uv (Python), npm (JavaScript) |
| Task queue | Celery + Redis (scheduled tasks only in Phase 1) |
| Printing | Local Python print agent (ESC/POS over LAN/USB) |

**What is NOT used in Phase 1:** Django REST Framework (installed from boilerplate but unused),
Vue, React, Socket.io, DaisyUI (exists in boilerplate templates but not used in new code).

**Reference codebases:** `references/erpnext-develop/` (ERPNext) and `references/ury-develop/`
(URY restaurant layer) are READ ONLY. Every feature is ported from these references before
being implemented in Django.

---

## 2. App Architecture

### Apps

The project is organised into 8 Django apps under `restpos/apps/`:

| App | Responsibility | FEATURES.md sections |
|---|---|---|
| `settings` | Restaurant config, branches, rooms, tables, POS profiles, production units | A1, A3, A4, D2 |
| `inventory` | Item master, item groups, warehouses, stock ledger, stock entries, valuation | A12 |
| `menu` | Menu definition, menu items, variants, add-ons, bundles, pricing | A2 |
| `staff` | Roles, POS opening/closing entries, cashier shifts, session management | A9, A17 |
| `payments` | Payment modes, GL mapping, change calculation, discounts, rounding, write-offs | A10 |
| `orders` | Orders, order items, customer cards, KOT generation, ticket diffing, table transfer, cancellation, refunds | A6, A7, A18 |
| `printing` | Print agent client, ESC/POS formatting, ticket/receipt formats, printer config | A8 |
| `reports` | Daily P&L, sales reports, stock reports, departmental split, customer reports | A14, A15, A16 |

### Dependency Graph

```
settings R1 → inventory → menu → staff ↘
                         payments core ↗    settings R2 → orders → printing → reports
                                                                    refunds (cross-app)
```

**Build order reasoning:**
- `settings R1` first — every other app references branches, rooms, and tables
- `inventory` before `menu` — menu items reference the Item master
- `menu` before `orders` — orders contain menu items
- `payments core` is standalone (no deps); built before `staff` because `OpeningPayment.mode_of_payment` is a FK to `ModeOfPayment`
- `staff` needs `settings R1` (Branch) and `payments core` (ModeOfPayment); is built before `orders` because the order-app validate path enforces "exactly one Open shift per branch"
- `settings R2` needs menu (ItemGroup), inventory (Warehouse), payments (ModeOfPayment), and staff (POSProfile.applicable_users; the `pos_profile` FK is backfilled onto `POSOpeningEntry` here)
- `orders` is the central app — needs settings (R1+R2), menu, staff, and payments
- `printing` needs orders (ticket data to format and print)
- `reports` needs everything
- `refunds` extends orders/payments/inventory (reversal entries)

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
| 1 | settings R1 | A1, D2 (partial) | Branch, Room, Table, Restaurant, UserRoomAssignment | None | complete |
| 2 | inventory | A12 | Item, ItemGroup, Warehouse, StockLedgerEntry, StockEntry, UOM, Bin, ProductBundle, StockReconciliation | settings R1 | complete |
| 3 | menu | A2 | Menu, MenuItem, PriceList, ItemPrice, ItemAddOn, ItemVariant | inventory | complete (MenuCourse removed) |
| 4 | payments core | A10 (partial) | ModeOfPayment, PaymentGLMapping | None (standalone) | complete (43 tests passing, migrations applied) |
| 5 | staff | A9, A17 | POSOpeningEntry, POSClosingEntry, OpeningPayment, ClosingPayment | settings R1, payments core | complete (58 tests passing, 472 total) |
| 6 | settings R2 | A3, A4, A5 (partial) | POSProfile, POSProfileUser, POSProfilePayment, ProductionUnit, TaxTemplate, TaxRate | menu, inventory, payments, staff | complete |
| 7 | orders | A6, A7, A18 | Order, OrderItem, KOT, Ticket, RefundOrder, RefundPaymentEntry | settings (R1+R2), menu, staff, payments | not started |
| 8 | printing | A8 | PrintAgent client, ESC/POS formatter, PrinterConfig | orders | not started |
| 9 | reports | A14, A15, A16 | DailyP&L, SalesReport, StockReport, DepartmentalReport | all apps | not started |
| 10 | refunds | A18 | Refund flow completion (reversal entries, stock restoration) | orders, payments, inventory | not started |

> **Phase 4/5 reordering note:** Payments Core is built before Staff because `OpeningPayment.mode_of_payment`
> is a FK to `payments.ModeOfPayment`. Payments Core is standalone (no dependencies), so promoting it
> ahead of Staff removes the only forward dependency and keeps Staff free of stub models. Staff's
> original Phase 4 designation becomes Phase 5. POSProfile FK on `POSOpeningEntry` is **deferred to
> Phase 6** via a migration (Phase 5 identifies shifts by branch alone for single-site Phase 1).

### Status values

- **not started** — no work done yet
- **planned** — detailed plan written in Section 6, ready to implement
- **in progress** — implementation underway
- **complete** — implementation done, tests passing, lint clean

---

## 4. App Summaries

### settings (Phases 1 + 6)

**Scope:** Restaurant configuration, branches, rooms, tables with floor-plan layout, POS profiles
(terminal configuration), production units (kitchen/bar stations with printer assignment),
tax templates.

**Split into two rounds:**
- Round 1 (Phase 1): Branch, Room, Table, Restaurant, UserRoomAssignment — no external dependencies
- Round 2 (Phase 6): POSProfile, ProductionUnit, TaxTemplate — needs menu's
  ItemGroup, inventory's Warehouse, payments' ModeOfPayment

**Key reference doctypes:** URY Restaurant, URY Room, URY Table, URY Production Unit, URY Printer
Settings, URY User, ERPNext POS Profile, ERPNext Branch

### inventory (Phase 2)

**Scope:** Item master (products), item groups (flat categories), warehouses, stock ledger
entries (immutable movement records), stock entries (manual movements), stock
reconciliation, valuation methods (FIFO/moving average). Single UOM per item — no conversions needed.
Batch tracking, product bundles, barcodes, reorder levels all removed (unnecessary for restaurant use).

**Key models:** Item, ItemGroup, Warehouse, StockLedgerEntry, StockEntry,
StockReconciliation, PurchaseReceipt, Bin

**Key reference doctypes:** ERPNext Item, Item Group, Warehouse, Stock Ledger Entry, Stock Entry,
Stock Reconciliation, UOM Conversion, Sales BOM

### menu (Phase 3)

**Scope:** Menu definition (collection of items per branch), menu items (links Item master to a
selling rate), special dish flag, item disable, item images, POS variants (Quarter/Half/Full),
POS add-ons, product bundles.

**Key models:** Menu, MenuItem, ItemVariant, ItemAddOn, ProductBundle, ProductBundleItem

**Key reference doctypes:** URY Menu, URY Menu Item, URY Menu Course, Item Add On, ERPNext Item
Variant, Sales BOM

### payments core (Phase 4)

**Scope:** Payment modes (Cash, Bank, General, Phone) as a flat master, GL account mapping per
company (account name as a CharField — Phase 9 introduces a real `LedgerAccount` and migrates to
a FK), `enabled` toggle. **Phase 4 covers modes and GL mapping only** — change calculation,
outstanding amount, discounts, rounding, write-off, and split-payment UI live in the orders app
(Phase 7).

**Key models:** ModeOfPayment, PaymentGLMapping

**Key reference doctypes:** ERPNext Mode of Payment, Mode of Payment Account, URY POS Profile
payment-method resolution

### staff (Phase 5)

**Scope:** Single shared cashier shift per branch (FEATURES.md #85). POS opening entries (shift
start with float per payment method), POS closing entries (shift end with reconciliation
between opening float, expected sales, and cashier-counted amounts). Manager + Cashier roles
can both open/close. The role-group conventions (Admin / Manager / Cashier) already live in
`apps/users` and the settings-app staff list; this phase enforces `has_staff_role` on the
shift-management views.

**Key models:** POSOpeningEntry, POSClosingEntry, OpeningPayment, ClosingPayment

**Key reference doctypes:** ERPNext POS Opening Entry, POS Closing Entry, URY User, Role
Permitted, URY hooks for opening/closing validation

**Phase 1 simplifications (documented in §6.5 Deviations):** no multi-cashier / Sub POS Closing,
no async / Queued/Failed consolidation, no daily-close "5 AM day boundary" check, no Order FK
on the closing entry totals, no `pos_profile` FK on the opening entry (deferred to Phase 6).

### orders (Phase 7)

**Scope:** The central app. Order sync (create/update draft invoices), table order loading, order
type detection, table restriction, price list resolution, invoice print before submit, item
modification lock, sequential order numbering, table transfer, captain transfer, cancel order,
cancel KOT, settle order, concurrent modification check, billing role check, customer favourite
items, KOT generation and diffing, ticket routing by department, ticket type detection, cancel
ticket creation, ticket reprint, duplicate ticket detection (Celery beat), ticket delay
notification, ticket status types, ticket grouping by customer card, customer cards / group
ordering (guest count, active card state, customer index on items), refund flow (full/partial
refunds, reversal payment entries, stock restoration, refund permission).

**Key models:** Order, OrderItem, KOT, KOTItem, RefundEntry, RefundPaymentEntry, RefundStockEntry

**Key reference doctypes:** ERPNext POS Invoice, POS Invoice Item, URY Order, URY Order Item, URY
KOT, URY KOT Items, URY hooks for order/KOT/invoice events

### printing (Phase 8)

**Scope:** Three thermal printers (cashier USB, kitchen LAN, bar LAN), Python print agent
(localhost HTTP → ESC/POS → printer), print job routing, print status update, printer
configuration (IP in DB on production unit), print formats (receipt, kitchen ticket, bar ticket).

**Key models:** PrintJob, PrinterConfig (may live on ProductionUnit in settings)

**Key reference doctypes:** URY Printer Settings, Network Printer Settings (Frappe core), URY print
hooks

### reports (Phase 9)

**Scope:** Today's sales, daywise/monthwise/item-wise/employee-wise/service-wise/time-wise sales,
cancelled invoices, customer data, repeated customers, average bill value, departmental sales
split, stock ledger report, stock balance report, stock ageing report, POS register, customer
credit balance, daily P&L (COGS, direct expenses, employee costs, indirect expenses, materials
consumed, electricity tracking, extended hours, P&L amendment), track changes, amendment chain.

**Key models:** DailyP&L, P&LLineItem, P&LAmendment (or calculations done as queries without
persistent models — to be decided during Phase 9 planning)

**Key reference doctypes:** URY Daily P&L, URY P&L doctypes (materials, COGS, expenses), ERPNext
Sales Invoice reports, Stock Ledger reports

### refunds (Phase 10)

**Scope:** Completing the refund flow from A18. Refund order (full/partial), refund payment entry
(reversal GL posting), refund stock restoration (positive stock ledger entries or wastage
posting), refund permission (Manager only by default). Cross-app: touches orders, payments,
inventory.

**Key models:** RefundEntry, RefundPaymentEntry, RefundStockEntry (may be part of orders app)

**Key reference doctypes:** ERPNext Payment Entry (reversal), Stock Ledger Entry (positive entry)

---

## 5. Session Continuity Protocol

When starting a new session to continue RestPOS implementation:

1. **Read project context:** Read `AGENTS.md`, `FEATURES.md`, and this `PLAN.md` to ground
   yourself in the current state.

2. **Check recent work:** Run `git log --oneline -10` to see what was done recently.

3. **Check database state:** Run `make manage ARGS='showmigrations'` to see which apps have
   migrations applied.

4. **Find current phase:** Check the status table in Section 3 above. Find the first phase
   that is "planned" (detailed plan exists in Section 6, ready to implement) or "in progress".

5. **Read the detailed plan:** Go to the corresponding subsection in Section 6 for the current
   phase. Read the model definitions, views, templates, tests, and reference files.

6. **If no detailed plan exists:** The phase status will be "not started". Before implementing,
   research the reference codebases (ERPNext and URY doctypes listed in the app summary) and
   write a detailed plan for that phase in Section 6, following the same structure as Section 6.1.

7. **After completing a phase:** Update the status in the Section 3 table from "in progress" to
   "complete", and set the next phase to "planned" if its detailed plan exists, or "not started"
   if it needs to be written.

8. **Always:** Run `make ruff` and `make test` after any code changes. Never commit unless
   explicitly asked.

---

## 5.5 Cross-cutting UI Conventions

> **Backoffice sidebar structure** (settled in the Phase 5 follow-up):
> - **Backoffice group** (Manager/Admin only): Dashboard, Settings, Inventory, Menu
> - **POS sub-header** (under Backoffice): Payments, Shifts, + Phase 6 will add POS Profile + POS Settings here
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
> `/backoffice/operations-dashboard/` page in Phase 7+ once orders and reports exist.
>
> **ERPNect vs RestPOS deviation:** ERPNext puts Mode of Payment in the Accounts Setup workspace
> (configuration), not in the POS section. RestPOS Phase 1 groups it under POS because that's
> the only place it's used (shift floats) and there's no separate Accounts app. Documented
> in `apps/web/views.py` and `templates/web/app/app_base.html` code comments.

---

## 6. Detailed Plans

### 6.1 Settings App — Round 1 (Phase 1)

**Status:** complete — 91 tests passing, lint clean, migrations applied
**FEATURES.md sections:** A1 (Restaurant Configuration), D2 (Branch / Location Management, partial)
**Dependencies:** None — this is the foundation phase.

#### Reference files consulted

| Reference file | What was extracted |
|---|---|
| `references/erpnext-develop/erpnext/setup/doctype/branch/branch.json` | Branch model (single field) |
| `references/erpnext-develop/erpnext/setup/doctype/branch/branch.py` | Branch logic (empty) |
| `references/ury-develop/ury/ury/doctype/ury_restaurant/ury_restaurant.json` | Restaurant fields |
| `references/ury-develop/ury/ury/doctype/ury_restaurant/ury_restaurant.py` | Restaurant logic (empty) |
| `references/ury-develop/ury/ury/doctype/ury_room/ury_room.json` | Room fields |
| `references/ury-develop/ury/ury/doctype/ury_room/ury_room.py` | Room logic (empty) |
| `references/ury-develop/ury/ury/doctype/ury_table/ury_table.json` | Table fields (layout, occupied, takeaway) |
| `references/ury-develop/ury/ury/doctype/ury_table/ury_table.py` | Table logic (broken autoname — JSON is authoritative) |
| `references/ury-develop/ury/ury/doctype/ury_user/ury_user.json` | User-room assignment model |
| `references/ury-develop/ury/ury/doctype/ury_user/ury_user.py` | User logic (empty) |
| `references/ury-develop/ury/fixtures/custom_field.json` | URY custom fields on Branch |
| `references/ury-develop/ury/ury_pos/api.py` | How user→room→branch resolution works |

#### Models

All models extend `apps.utils.models.BaseModel` (adds `created_at`, `updated_at`).

##### Branch (`settings.Branch`)

| Field | Type | Source | Notes |
|---|---|---|---|
| name | CharField, max_length=100, unique | ERPNext Branch.branch | e.g. "Main Branch" |

**Methods:**
- `__str__` returns `name`
- No validation beyond field constraints

##### Room (`settings.Room`)

| Field | Type | Source | Notes |
|---|---|---|---|
| branch | ForeignKey→Branch, on_delete=PROTECT | URY Room.branch | required |
| name | CharField, max_length=100 | URY Room (prompt naming) | e.g. "Main Dining", "Bar" |
| room_type | CharField, max_length=10, choices: AC, NON_AC, blank=True | URY Room.room_type | optional |

**Methods:**
- `__str__` returns `name`
- No validation beyond field constraints
- `Meta.unique_together`: `(branch, name)` — no duplicate room names within a branch

##### Table (`settings.Table`)

| Field | Type | Source | Notes |
|---|---|---|---|
| room | ForeignKey→Room, on_delete=PROTECT | URY Table.restaurant_room | required |
| branch | ForeignKey→Branch, on_delete=PROTECT | URY Table.branch (fetch_from) | denormalized for query efficiency |
| name | CharField, max_length=50 | URY Table (prompt naming) | e.g. "T1" |
| no_of_seats | IntegerField, null=True, blank=True | URY Table.no_of_seats | |
| minimum_seating | IntegerField, null=True, blank=True | URY Table.minimum_seating | |
| table_shape | CharField, max_length=20, choices: RECTANGLE, SQUARE, CIRCLE, blank=True | URY Table.table_shape | |
| is_take_away | BooleanField, default=False | URY Table.is_take_away | virtual tables for takeaway orders |
| occupied | BooleanField, default=False, editable=False | URY Table.occupied | system-managed — set by orders app |
| latest_invoice_time | DateTimeField, null=True, blank=True, editable=False | URY Table.latest_invoice_time | system-managed |
| layout_x | FloatField, null=True, blank=True | URY Table.layout_x | floor plan position |
| layout_y | FloatField, null=True, blank=True | URY Table.layout_y | floor plan position |
| layout_width | FloatField, null=True, blank=True | URY Table.layout_width | floor plan size |
| layout_height | FloatField, null=True, blank=True | URY Table.layout_height | floor plan size |

**Methods:**
- `__str__` returns `name`
- `occupied` and `latest_invoice_time` are `editable=False` — updated by the orders app
- `Meta.unique_together`: `(room, name)` — no duplicate table names within a room

**Deviation from URY:** URY Table links to URY Restaurant (required). RestPOS Table links to
Room (required) and Branch (denormalized). The Restaurant link is dropped because RestPOS has
a single Restaurant per branch (singleton), and the branch is already reachable via `room.branch`.

##### Restaurant (`settings.Restaurant`)

| Field | Type | Source | Notes |
|---|---|---|---|
| company | CharField, max_length=200 | URY Restaurant.company | no Company model in Phase 1 — just a name |
| branch | ForeignKey→Branch, on_delete=PROTECT | URY Restaurant.branch | required |
| invoice_series_prefix | CharField, max_length=20, default="REST-" | URY Restaurant.invoice_series_prefix | #1 |
| address | TextField, blank=True | URY Restaurant.address | simplified to text (no Address model) |
| default_room | ForeignKey→Room, on_delete=PROTECT | URY Restaurant.default_room | required |
| active_menu | ForeignKey→menu.Menu, null=True, blank=True | URY Restaurant.active_menu | set when menu app is built |
| default_tax_template | ForeignKey→settings.TaxTemplate, null=True, blank=True | URY Restaurant.default_tax_template | set in Round 2 |

**Methods:**
- `__str__` returns `company` or `self.branch.name`
- `clean()`: validate only one Restaurant per branch (singleton per branch)
- `clean()`: validate `self.default_room.branch == self.branch`

**Deviations from URY:**
- `room_wise_menu` and `order_type_wise_menu` omitted — FEATURES.md #7 says "There is a single
  menu for the restaurant; every room and order type uses the same menu."
- `company` is a CharField, not a Link→Company — no Company model in Phase 1
- `address` is a TextField, not a Link→Address — no Address model in Phase 1

##### UserRoomAssignment (`settings.UserRoomAssignment`)

| Field | Type | Source | Notes |
|---|---|---|---|
| user | ForeignKey→CustomUser, on_delete=CASCADE | URY User.user | required |
| room | ForeignKey→Room, on_delete=CASCADE | URY User.room | required |
| branch | ForeignKey→Branch, on_delete=CASCADE | derived from room.branch | denormalized for query efficiency |

**Methods:**
- `__str__` returns `f"{user.username} → {room.name}"`
- `clean()`: validate `self.room.branch == self.branch` (consistency check)
- `clean()`: validate no duplicate user+room pairs
- `Meta.unique_together`: `(user, room)`

**Deviation from URY:** URY uses a child table (URY User) on Branch. RestPOS uses a standalone
through model — cleaner in Django ORM and easier to query ("which rooms can this user see?").

#### Views & URLs

Function-based views with HTMX partial updates. All require login.

| URL pattern | View function | Purpose |
|---|---|---|
| `/backoffice/settings/` | `settings_dashboard` | Overview landing page |
| `/backoffice/settings/branches/` | `branch_list` | List all branches |
| `/backoffice/settings/branches/create/` | `branch_create` | Create branch (HTMX modal) |
| `/backoffice/settings/branches/<int:pk>/` | `branch_detail` | View/edit branch |
| `/backoffice/settings/branches/<int:pk>/edit/` | `branch_update` | Update branch (HTMX) |
| `/backoffice/settings/rooms/` | `room_list` | List rooms (filterable by branch) |
| `/backoffice/settings/rooms/create/` | `room_create` | Create room |
| `/backoffice/settings/rooms/<int:pk>/` | `room_detail` | View/edit room |
| `/backoffice/settings/rooms/<int:pk>/edit/` | `room_update` | Update room |
| `/backoffice/settings/tables/` | `table_list` | List tables (filterable by room) |
| `/backoffice/settings/tables/create/` | `table_create` | Create table |
| `/backoffice/settings/tables/<int:pk>/` | `table_detail` | View/edit table |
| `/backoffice/settings/tables/<int:pk>/edit/` | `table_update` | Update table |
| `/backoffice/settings/tables/<int:pk>/layout/` | `table_update_layout` | Save floor-plan coordinates (HTMX POST) |
| `/backoffice/settings/restaurant/` | `restaurant_detail` | View restaurant config (singleton per branch) |
| `/backoffice/settings/restaurant/edit/` | `restaurant_update` | Update restaurant config |
| `/backoffice/settings/users/` | `user_room_list` | List user-room assignments |
| `/backoffice/settings/users/create/` | `user_room_create` | Assign user to room |
| `/backoffice/settings/users/<int:pk>/edit/` | `user_room_update` | Edit assignment |
| `/backoffice/settings/users/<int:pk>/delete/` | `user_room_delete` | Remove assignment |

#### Templates

All templates go in `templates/backoffice/settings/`. Pure Tailwind CSS (no DaisyUI). Use Django
6.0 template partials for HTMX response fragments. Base template: `web/app/app_base.html`.

| Template | Purpose |
|---|---|
| `templates/backoffice/settings/dashboard.html` | Overview landing page |
| `templates/backoffice/settings/branch_list.html` | Branch list with `{% partialdef row %}` per row |
| `templates/backoffice/settings/branch_form.html` | Create/edit branch (modal or inline) |
| `templates/backoffice/settings/room_list.html` | Room list with branch filter |
| `templates/backoffice/settings/room_form.html` | Create/edit room |
| `templates/backoffice/settings/table_list.html` | Table list with room filter |
| `templates/backoffice/settings/table_form.html` | Create/edit table |
| `templates/backoffice/settings/table_layout.html` | Floor-plan editor (drag-and-drop) |
| `templates/backoffice/settings/restaurant_detail.html` | Restaurant config view/edit |
| `templates/backoffice/settings/user_room_list.html` | User-room assignment list |
| `templates/backoffice/settings/user_room_form.html` | Assign/edit user-room |

#### Table Layout Editor (#4)

The floor-plan editor is the most complex UI component in Round 1:
- **HTML5 drag API** (via Alpine.js directives) for drag/move/resize
- **HTMX** to save coordinates via `table_update_layout` view (POST with x, y, width, height)
- CSS-grid or absolute-positioned background for the room floor plan
- Zoom/pan via Alpine.js state
- Shape icons (rectangle, square, circle) rendered with Tailwind/SVG

#### Forms

Use Django `ModelForm` for each model. Validation logic in the form's `clean()` and
`clean_<field>()` methods, not in views.

| Form | Model | Notes |
|---|---|---|
| `BranchForm` | Branch | |
| `RoomForm` | Room | Branch field may be hidden if user has only one branch |
| `TableForm` | Table | Branch auto-set from selected room |
| `RestaurantForm` | Restaurant | Branch field read-only (singleton per branch) |
| `UserRoomAssignmentForm` | UserRoomAssignment | Branch auto-set from selected room |

#### Admin

Register all 5 models in `settings/admin.py` with `list_display`, `list_filter`, and
`search_fields` for back-office admin access.

#### Tests

| Test file | What it covers |
|---|---|
| `settings/tests/test_branch.py` | Branch CRUD |
| `settings/tests/test_room.py` | Room CRUD, branch relationship, unique_together |
| `settings/tests/test_table.py` | Table CRUD, shape choices, takeaway flag, layout coordinates, editable=False on occupied |
| `settings/tests/test_restaurant.py` | Restaurant singleton per branch, default_room.branch consistency, prefix defaults |
| `settings/tests/test_user_room_assignment.py` | User-room mapping, duplicate prevention, branch consistency |
| `settings/tests/test_views.py` | View-level tests: list, create, edit, delete for each model; login required; HTMX partial responses |

Use Django's `TestCase` for database tests. Test both happy path and error/edge cases.

#### Deviations from reference — summary

| Deviation | Reason |
|---|---|
| `room_wise_menu` and `order_type_wise_menu` omitted | FEATURES.md #7: single menu for all rooms/order types |
| `UserRoomAssignment` is standalone, not child table on Branch | Django ORM pattern — cleaner queries |
| `address` is TextField, not Link→Address | No Address model in Phase 1 |
| `company` is CharField, not Link→Company | No Company model in Phase 1 |
| `occupied` and `latest_invoice_time` are `editable=False` | System-managed, prevents manual override |
| Printer settings NOT on Room | RestPOS routes by department flag (#68), printer config on ProductionUnit (#16) |
| Table links to Room (not Restaurant) | Branch reachable via room.branch; single Restaurant per branch |
| Branch kept in DB but hidden in Phase 1 UI; auto-set via `Branch.get_default()` (or derived from room) on Menu, Room, Warehouse, Restaurant; Table/UserRoomAssignment derive branch from room | Single-site restaurant; multi-branch isolation remains available without cashier-facing branch pickers |

#### Implementation steps

1. Create the `settings` app: `make uv run 'pegasus startapp settings Branch Room Table Restaurant UserRoomAssignment'`
2. Write models in `apps/settings/models.py`
3. Write forms in `apps/settings/forms.py`
4. Write views in `apps/settings/views.py`
5. Write URLs in `apps/settings/urls.py`
6. Register in `apps/settings/admin.py`
7. Add `apps.settings` to `INSTALLED_APPS` in `restpos/settings.py`
8. Include settings URLs in `restpos/urls.py`
9. Write templates in `templates/backoffice/settings/`
10. Create and run migrations: `make migrations && make migrate`
11. Write tests: `apps/settings/tests/`
12. Run tests: `make test ARGS='apps.settings'`
13. Run lint: `make ruff`

---

### 6.2 Inventory App (Phase 2)

**Status:** planned
**FEATURES.md sections:** A12
**Dependencies:** settings R1 (Branch)

#### Decisions

- **Stock tracking:** Uses FIFO and moving average valuation
- **Item variants:** Fields on Item only (`has_variants`, `variant_of`). No ItemAttribute/ItemVariantAttribute models. Variant selection handled in menu app (Phase 3).
- **Tree structure:** Simple parent ForeignKey (self-referential). No django-mptt or treebeard.
- **UOM:** Separate master model, seeded with common restaurant UOMs.

#### Reference files consulted

| Reference file | What was extracted |
|---|---|
| `references/erpnext-develop/erpnext/stock/doctype/item/item.json` | Item fields (60+ — filtered to ~20 for POS) |
| `references/erpnext-develop/erpnext/stock/doctype/item/item.py` | Item validation logic |
| `references/erpnext-develop/erpnext/stock/doctype/item_barcode/item_barcode.json` | Barcode child table |
| `references/erpnext-develop/erpnext/stock/doctype/item_reorder/item_reorder.json` | Reorder level child table |
| `references/erpnext-develop/erpnext/stock/doctype/uom_conversion_detail/uom_conversion_detail.json` | UOM conversion child table |
| `references/erpnext-develop/erpnext/setup/doctype/item_group/item_group.json` | Item Group tree structure |
| `references/erpnext-develop/erpnext/stock/doctype/warehouse/warehouse.json` | Warehouse doctype |
| `references/erpnext-develop/erpnext/stock/doctype/stock_ledger_entry/stock_ledger_entry.json` | SLE fields |
| `references/erpnext-develop/erpnext/stock/doctype/stock_ledger_entry/stock_ledger_entry.py` | SLE validation |
| `references/erpnext-develop/erpnext/stock/doctype/stock_entry/stock_entry.json` | Stock Entry fields and purposes |
| `references/erpnext-develop/erpnext/stock/doctype/stock_entry/stock_entry.py` | Stock Entry submit/cancel logic |
| `references/erpnext-develop/erpnext/stock/doctype/stock_entry_detail/stock_entry_detail.json` | Stock Entry line items |
| `references/erpnext-develop/erpnext/stock/doctype/bin/bin.json` | Bin cache table fields |
| `references/erpnext-develop/erpnext/stock/doctype/stock_reconciliation/stock_reconciliation.json` | Reconciliation fields |
| `references/erpnext-develop/erpnext/stock/doctype/stock_reconciliation_item/stock_reconciliation_item.json` | Reconciliation line items |
| `references/erpnext-develop/erpnext/selling/doctype/product_bundle/product_bundle.json` | Product bundle parent |
| `references/erpnext-develop/erpnext/selling/doctype/product_bundle_item/product_bundle_item.json` | Product bundle components |
| `references/erpnext-develop/erpnext/stock/stock_ledger.py` | SLE creation and Bin update logic |
| `references/erpnext-develop/erpnext/stock/reorder_item.py` | Reorder level alert logic |
| `references/ury-develop/ury/ury/doctype/ury_order/ury_order.py` | How URY sets update_stock=1 |

#### Models (14 total)

All models extend `apps.utils.models.BaseModel`. Serial number tracking (#114) was removed from FEATURES.md by user decision — not implemented.

##### UOM (`inventory.UOM`)

| Field | Type | Notes |
|---|---|---|
| name | CharField, max_length=50, unique | e.g. "Each", "Kg", "Litre", "Case" |
| is_active | BooleanField, default=True | |

Seed data: Each, Kg, Gram, Litre, Millilitre, Case, Box, Dozen, Pack.

##### ItemGroup (`inventory.ItemGroup`)

| Field | Type | Notes |
|---|---|---|
| name | CharField, max_length=100, unique | e.g. "Food", "Beverages" |
| description | TextField, blank=True | |

**Methods:** `__str__` returns `name`.

##### Warehouse (`inventory.Warehouse`)

| Field | Type | Notes |
|---|---|---|
| name | CharField, max_length=100 | e.g. "Kitchen", "Bar", "Stores" |
| branch | ForeignKey→settings.Branch, on_delete=PROTECT, related_name="warehouses" | |
| disabled | BooleanField, default=False | |

**Methods:** `__str__` returns `name`. Meta: `unique_together = [("name", "branch")]`.

##### Item (`inventory.Item`)

| Field | Type | Notes |
|---|---|---|
| item_code | CharField, max_length=50, unique | The primary identifier |
| item_name | CharField, max_length=200 | Display name (auto-set to item_code if blank) |
| item_group | ForeignKey→ItemGroup, on_delete=PROTECT, related_name="items" | required |
| stock_uom | ForeignKey→UOM, on_delete=PROTECT, related_name="items" | required |
| department | CharField, max_length=10, choices=[("FOOD","Food"),("DRINKS","Drinks")] | required — #260 |
| image | ImageField, null=True, blank=True | Item image for POS |
| description | TextField, blank=True | |
| disabled | BooleanField, default=False | Disabled items can't be selected |
| is_stock_item | BooleanField, default=True | If False, no stock tracking |
| default_warehouse | ForeignKey→Warehouse, null=True, blank=True, on_delete=SET_NULL | |
| valuation_method | CharField, max_length=20, choices=[("FIFO","FIFO"),("MOVING_AVERAGE","Moving Average")], default="FIFO" | |
| has_variants | BooleanField, default=False | Template item — can't be sold directly |
| variant_of | ForeignKey→self, null=True, blank=True, on_delete=PROTECT, related_name="variants" | Set on variant items |
| safety_stock | DecimalField, max_digits=10, decimal_places=2, default=0 | Buffer stock |
| last_purchase_rate | DecimalField, max_digits=10, decimal_places=2, null=True, blank=True | Last purchase rate |

**Methods:**
- `__str__` returns `item_name or item_code`
- `clean()`: if `has_variants=True`, item cannot be `is_stock_item=True`
- `clean()`: if `variant_of` is set, validate parent has `has_variants=True`


##### ItemBarcode (`inventory.ItemBarcode`)

| Field | Type | Notes |
|---|---|---|
| item | ForeignKey→Item, on_delete=CASCADE, related_name="barcodes" | |
| barcode | CharField, max_length=100, unique | |
| barcode_type | CharField, max_length=20, blank=True | e.g. "EAN", "UPC-A", "CODE-39" |

##### ItemUOMConversion (`inventory.ItemUOMConversion`)

| Field | Type | Notes |
|---|---|---|
| item | ForeignKey→Item, on_delete=CASCADE, related_name="uom_conversions" | |
| uom | ForeignKey→UOM, on_delete=CASCADE | |
| conversion_factor | DecimalField, max_digits=10, decimal_places=4 | How many stock_uom = 1 of this uom |

**Validation:** stock_uom always has conversion_factor=1 (enforced in Item.clean). No duplicate UOMs per item.

##### ReorderLevel (`inventory.ReorderLevel`)

| Field | Type | Notes |
|---|---|---|
| item | ForeignKey→Item, on_delete=CASCADE, related_name="reorder_levels" | |
| warehouse | ForeignKey→Warehouse, on_delete=CASCADE | |
| reorder_level | DecimalField, max_digits=10, decimal_places=2, default=0 | When stock drops below this, alert |
| reorder_qty | DecimalField, max_digits=10, decimal_places=2, default=0 | How much to reorder |

**Meta:** `unique_together = [("item", "warehouse")]`

##### ProductBundle (`inventory.ProductBundle`)

| Field | Type | Notes |
|---|---|---|
| parent_item | ForeignKey→Item, on_delete=CASCADE, related_name="bundles" | The combo item (is_stock_item=False) |
| is_active | BooleanField, default=True | |

**Meta:** `unique_together = [("parent_item",)]` — one active bundle per parent item

##### ProductBundleItem (`inventory.ProductBundleItem`)

| Field | Type | Notes |
|---|---|---|
| bundle | ForeignKey→ProductBundle, on_delete=CASCADE, related_name="items" | |
| item | ForeignKey→Item, on_delete=PROTECT | Must be a leaf item (has_variants=False) |
| qty | DecimalField, max_digits=10, decimal_places=2 | Quantity of this component |

##### Bin (`inventory.Bin`)

Cache table — one row per item+warehouse. Auto-created by the stock ledger logic.

| Field | Type | Notes |
|---|---|---|
| item | ForeignKey→Item, on_delete=CASCADE | |
| warehouse | ForeignKey→Warehouse, on_delete=CASCADE | |
| actual_qty | DecimalField, max_digits=10, decimal_places=2, default=0 | Current stock on hand |
| reserved_qty | DecimalField, max_digits=10, decimal_places=2, default=0 | Reserved for draft POS invoices |
| valuation_rate | DecimalField, max_digits=10, decimal_places=2, default=0 | |
| stock_value | DecimalField, max_digits=12, decimal_places=2, default=0 | actual_qty * valuation_rate |

**Meta:** `unique_together = [("item", "warehouse")]`

**Class method:** `get_or_create(item, warehouse)` — returns existing Bin or creates one.

##### StockLedgerEntry (`inventory.StockLedgerEntry`)

Immutable stock movement record. Never created directly by users.

| Field | Type | Notes |
|---|---|---|
| item | ForeignKey→Item, on_delete=PROTECT, related_name="stock_ledger_entries" | |
| warehouse | ForeignKey→Warehouse, on_delete=PROTECT | |
| posting_datetime | DateTimeField, default=now, editable=False | |
| voucher_type | CharField, max_length=50 | "Stock Entry", "POS Invoice", "Stock Reconciliation" |
| voucher_no | CharField, max_length=100 | Parent document ID |
| voucher_detail_no | CharField, max_length=100, blank=True | Line item ID in parent |
| actual_qty | DecimalField, max_digits=10, decimal_places=2, editable=False | +in, -out |
| qty_after_transaction | DecimalField, max_digits=10, decimal_places=2, editable=False | Running balance |
| incoming_rate | DecimalField, max_digits=10, decimal_places=2, default=0, editable=False | |
| outgoing_rate | DecimalField, max_digits=10, decimal_places=2, default=0, editable=False | |
| valuation_rate | DecimalField, max_digits=10, decimal_places=2, default=0, editable=False | Rate after this entry |
| stock_value | DecimalField, max_digits=12, decimal_places=2, default=0, editable=False | |
| stock_queue | TextField, blank=True, default="" | JSON FIFO queue |
| is_cancelled | BooleanField, default=False, editable=False | |

**Class method:** `create_entry(item, warehouse, actual_qty, voucher_type, voucher_no, rate=0)` — creates SLE, updates Bin, recalculates qty_after_transaction and valuation_rate.

##### StockEntry (`inventory.StockEntry`)

Manual stock movement document. Submit/cancel workflow.

| Field | Type | Notes |
|---|---|---|
| purpose | CharField, max_length=30, choices=[("MATERIAL_RECEIPT","Material Receipt"),("MATERIAL_ISSUE","Material Issue"),("MATERIAL_TRANSFER","Material Transfer"),("REPACK","Repack")] | required |
| posting_date | DateField, default=today | |
| from_warehouse | ForeignKey→Warehouse, null=True, blank=True, on_delete=PROTECT, related_name="outgoing_stock_entries" | Source (for Issue/Transfer/Repack) |
| to_warehouse | ForeignKey→Warehouse, null=True, blank=True, on_delete=PROTECT, related_name="incoming_stock_entries" | Target (for Receipt/Transfer/Repack) |
| status | CharField, max_length=10, choices=[("DRAFT","Draft"),("SUBMITTED","Submitted"),("CANCELLED","Cancelled")], default="DRAFT" | |
| remarks | TextField, blank=True | |

**Methods:**
- `submit()`: set status to SUBMITTED, create SLEs for each detail line
- `cancel()`: set status to CANCELLED, create reversal SLEs
- `clean()`: validate from_warehouse/to_warehouse based on purpose (Receipt needs to, Issue needs from, Transfer needs both)

##### StockEntryDetail (`inventory.StockEntryDetail`)

| Field | Type | Notes |
|---|---|---|
| stock_entry | ForeignKey→StockEntry, on_delete=CASCADE, related_name="items" | |
| item | ForeignKey→Item, on_delete=PROTECT | |
| source_warehouse | ForeignKey→Warehouse, null=True, blank=True, on_delete=PROTECT | Overrides stock_entry.from_warehouse |
| target_warehouse | ForeignKey→Warehouse, null=True, blank=True, on_delete=PROTECT | Overrides stock_entry.to_warehouse |
| qty | DecimalField, max_digits=10, decimal_places=2 | required |
| uom | ForeignKey→UOM, on_delete=PROTECT | required |
| conversion_factor | DecimalField, max_digits=10, decimal_places=4, default=1 | |
| basic_rate | DecimalField, max_digits=10, decimal_places=2, default=0 | Cost per stock UOM |

##### StockReconciliation (`inventory.StockReconciliation`)

| Field | Type | Notes |
|---|---|---|
| purpose | CharField, max_length=20, choices=[("OPENING_STOCK","Opening Stock"),("RECONCILIATION","Stock Reconciliation")], default="RECONCILIATION" | |
| posting_date | DateField, default=today | |
| warehouse | ForeignKey→Warehouse, on_delete=PROTECT | |
| status | CharField, max_length=10, choices=[("DRAFT","Draft"),("SUBMITTED","Submitted"),("CANCELLED","Cancelled")], default="DRAFT" | |
| remarks | TextField, blank=True | |

##### StockReconciliationItem (`inventory.StockReconciliationItem`)

| Field | Type | Notes |
|---|---|---|
| reconciliation | ForeignKey→StockReconciliation, on_delete=CASCADE, related_name="items" | |
| item | ForeignKey→Item, on_delete=PROTECT | |
| warehouse | ForeignKey→Warehouse, on_delete=PROTECT | |
| qty | DecimalField, max_digits=10, decimal_places=2 | The counted quantity |
| current_qty | DecimalField, max_digits=10, decimal_places=2, default=0, editable=False | Auto-filled from Bin |
| valuation_rate | DecimalField, max_digits=10, decimal_places=2, null=True, blank=True | |

#### Business logic — StockLedgerEntry.create_entry

This is the core method that all stock movements funnel through:

```python
@classmethod
def create_entry(cls, item, warehouse, actual_qty, voucher_type, voucher_no, rate=0, voucher_detail_no=""):
    bin = Bin.get_or_create(item, warehouse)
    previous_qty = bin.actual_qty
    new_qty = previous_qty + actual_qty
    
    # FIFO queue management
    queue = json.loads(bin.stock_queue or "[]") if hasattr(bin, "stock_queue") else []
    # ... update queue based on actual_qty sign and rate
    
    # Create the SLE
    sle = cls.objects.create(
        item=item, warehouse=warehouse, actual_qty=actual_qty,
        qty_after_transaction=new_qty, voucher_type=voucher_type,
        voucher_no=voucher_no, voucher_detail_no=voucher_detail_no,
        incoming_rate=rate if actual_qty > 0 else 0,
        outgoing_rate=rate if actual_qty < 0 else 0,
        valuation_rate=bin.valuation_rate,
        stock_value=new_qty * bin.valuation_rate,
    )
    
    # Update Bin
    bin.actual_qty = new_qty
    bin.valuation_rate = ...  # recalculate
    bin.stock_value = bin.actual_qty * bin.valuation_rate
    bin.save()
    
    return sle
```

##### PurchaseReceipt (`inventory.PurchaseReceipt`)

Per FEATURES.md #123. Records goods received from a supplier. On submit, increases stock levels.

| Field | Type | Notes |
|---|---|---|
| supplier_name | CharField, max_length=200 | Supplier name (no Supplier model in Phase 1) |
| supplier_delivery_note | CharField, max_length=100, blank=True | Supplier's delivery note reference |
| posting_date | DateField, default=today | Date of receipt |
| warehouse | ForeignKey→Warehouse, on_delete=PROTECT, related_name="purchase_receipts" | Store room that receives the entire delivery |
| status | CharField, max_length=10, choices=[("DRAFT","Draft"),("SUBMITTED","Submitted"),("CANCELLED","Cancelled")], default="DRAFT" | |
| total | DecimalField, max_digits=12, decimal_places=2, default=0, editable=False | Sum of item amounts |
| remarks | TextField, blank=True | |

**Methods:**
- `__str__` returns `f"PR {self.supplier_name} {self.posting_date}"`
- `submit()`: set status to SUBMITTED, create SLEs for each item (actual_qty=+received_qty to purchase_receipt.warehouse)
- `cancel()`: set status to CANCELLED, create reversal SLEs
- `clean()`: warehouse is required

##### PurchaseReceiptItem (`inventory.PurchaseReceiptItem`)

| Field | Type | Notes |
|---|---|---|
| purchase_receipt | ForeignKey→PurchaseReceipt, on_delete=CASCADE, related_name="items" | |
| item | ForeignKey→Item, on_delete=PROTECT | |
| received_qty | DecimalField, max_digits=10, decimal_places=2 | Quantity entering stock (omit damaged/refused goods) |
| rate | DecimalField, max_digits=10, decimal_places=2 | Cost per unit |
| amount | DecimalField, max_digits=12, decimal_places=2, default=0, editable=False | received_qty * rate (auto-calculated) |

No per-line warehouse — the whole receipt posts to `PurchaseReceipt.warehouse`. Store → kitchen (etc.) moves use Stock Entry.

**Methods:**
- `save()`: auto-calculate amount = received_qty * rate

#### Business logic — StockLedgerEntry.create_entry

| URL pattern | View | Purpose |
|---|---|---|
| `/backoffice/inventory/` | `inventory_dashboard` | Overview with low-stock alerts |
| `/backoffice/inventory/uoms/` | `uom_list` / `uom_create` / `uom_update` | UOM CRUD |
| `/backoffice/inventory/item-groups/` | `item_group_list` / `item_group_create` / `item_group_detail` / `item_group_update` | Item Group CRUD (tree view) |
| `/backoffice/inventory/warehouses/` | `warehouse_list` / `warehouse_create` / `warehouse_detail` / `warehouse_update` | Warehouse CRUD |
| `/backoffice/inventory/items/` | `item_list` / `item_create` / `item_detail` / `item_update` | Item CRUD (with barcodes, UOMs, reorder levels as inline formsets) |
| `/backoffice/inventory/bundles/` | `product_bundle_list` / `product_bundle_create` / `product_bundle_detail` / `product_bundle_update` | Product Bundle CRUD |
| `/backoffice/inventory/stock-entries/` | `stock_entry_list` / `stock_entry_create` / `stock_entry_detail` / `stock_entry_submit` / `stock_entry_cancel` | Stock Entry create + submit/cancel |
| `/backoffice/inventory/reconciliations/` | `reconciliation_list` / `reconciliation_create` / `reconciliation_detail` / `reconciliation_submit` / `reconciliation_cancel` | Stock Reconciliation create + submit/cancel |
| `/backoffice/inventory/purchase-receipts/` | `purchase_receipt_list` / `purchase_receipt_create` / `purchase_receipt_detail` / `purchase_receipt_submit` / `purchase_receipt_cancel` | Purchase Receipt create + submit/cancel (#123) |
| `/backoffice/inventory/stock-ledger/` | `stock_ledger_list` | SLE report (read-only, filterable by item/warehouse/date) |
| `/backoffice/inventory/stock-balance/` | `stock_balance_list` | Current stock per item per warehouse (from Bin) |

#### Tests

| Test file | What it covers |
|---|---|
| `test_uom.py` | UOM CRUD |
| `test_item_group.py` | Item Group CRUD, parent/child tree, is_group flag |
| `test_warehouse.py` | Warehouse CRUD, branch link |
| `test_item.py` | Item CRUD, department choices, variant validation, barcode/UOM/reorder child tables |
| `test_bin.py` | Bin auto-creation, get_or_create, actual_qty updates |
| `test_stock_ledger_entry.py` | SLE creation, qty_after_transaction running balance, Bin update, cancellation reversal |
| `test_stock_entry.py` | Stock Entry CRUD, submit creates SLEs, cancel reverses, purpose validation (from/to warehouse) |
| `test_stock_reconciliation.py` | Reconciliation submit adjusts stock, cancel reverses |
| `test_product_bundle.py` | Bundle CRUD, component validation |
| `test_views.py` | View-level tests: login required, list/create/submit/cancel, filtering |

#### Deviations from reference

| Deviation | Reason |
|---|---|---|
| ItemAttribute/ItemVariantAttribute excluded | Variants handled via simple parent FK on Item; menu app handles selection |
| No tree library (mptt/treebeard) | Flat models — restaurant categories and warehouses are simple enough not to need deep nesting |
| Accounting fields dropped (expense_account, income_account, cost_center, etc.) | Accounting handled at POS Profile / restaurant config level |
| Purchase Receipt rejected_warehouse / rejected_qty / accepted_qty dropped | Phase 1: only book what enters sellable stock. Damaged goods at receipt are omitted from the PR; later write-offs use Stock Reconciliation or Material Issue. ERPNext dual accepted/rejected path is overkill for a single-branch restaurant. |
| Purchase Receipt warehouse only on parent (no item warehouse); renamed accepted_warehouse → warehouse | Restaurant receives into one store room per delivery; item-level override is an ERPNext footgun. Internal moves use Stock Entry (Material Transfer / Issue). |
| Manufacturing fields dropped (BOM, work_order, subcontract) | Not applicable to a restaurant |
| Fixed asset fields dropped | Not applicable |
| UOM Conversion dropped | Items use a single stock_uom — the practical unit used in the kitchen (Mudu, Kg, Pieces). No conversions needed |
| Batches, barcodes, product bundles, reorder levels dropped | Removed as unnecessary for restaurant operations — kitchen manager tracks consumption manually |
| Bin simplified (no ordered_qty, indented_qty, planned_qty) | Restaurant doesn't use purchase orders or work orders in Phase 1 |
| `department` field added to Item | RestPOS-specific: FOOD/DRINKS classification (#260) — not in ERPNext |
| `last_purchase_rate` auto-updated on Purchase Receipt | ERPNext naming: standard_rate = selling price; last_purchase_rate = auto-updated cost from buying transactions |
| 3-tier roles (Admin/Manager/Cashier) | Only superusers can assign roles. Admin → Manager → Cashier hierarchy |

---

### 6.3 Menu App (Phase 3)

**Status:** complete — 90 tests passing, lint clean, migrations applied

#### Reference files consulted

| Reference file | What was extracted |
|---|---|
| `references/ury-develop/ury/ury/doctype/ury_menu/ury_menu.json` | Menu fields and price list auto-creation |
| `references/ury-develop/ury/ury/doctype/ury_menu/ury_menu.py` | Menu validate + make_price_list logic |
| `references/ury-develop/ury/ury/doctype/ury_menu_item/ury_menu_item.json` | MenuItem fields (rate, special_dish, disabled, course) |
| `references/ury-develop/ury/ury/doctype/ury_menu_course/ury_menu_course.json` | Studied but rejected — MenuCourse not in FEATURES.md |
| `references/ury-develop/ury/ury/doctype/item_add_on/item_add_on.json` | Add-on child table structure |
| `references/ury-develop/ury/ury/doctype/pos_item_variants/pos_item_variants.json` | POS variant child table structure |
| `references/erpnext-develop/erpnext/stock/doctype/item_price/item_price.json` | ItemPrice fields |
| `references/erpnext-develop/erpnext/stock/doctype/item_price/item_price.py` | ItemPrice validation |
| `references/erpnext-develop/erpnext/stock/doctype/price_list/price_list.json` | PriceList fields |
| `references/ury-develop/ury/ury_pos/api.py` | getRestaurantMenu — how POS loads menu items |
| `references/ury-develop/ury/ury/hooks/ury_item.py` | Add-on/variant integrity validation |
| `references/ury-develop/pos/src/components/ProductDialog.tsx` | How add-ons/variants are priced on POS |

#### Models (6 total)

All models extend `apps.utils.models.BaseModel`.

> **Note:** MenuCourse was removed — it is NOT in FEATURES.md. The category sidebar (#195) uses Item Groups, not courses.

##### Menu (`menu.Menu`)

| Field | Type | Notes |
|---|---|---|
| name | CharField, max_length=100 | e.g. "Main Menu", "Lunch Menu" |
| branch | ForeignKey→settings.Branch, on_delete=PROTECT, related_name="menus" | Required in DB; Phase 1 UI hides it and auto-assigns via `Branch.get_default()` |
| enabled | BooleanField, default=True | Disabled menus hide all items from POS |

**Methods:**
- `__str__` returns `name`
- `save()`: if branch unset, assign `Branch.get_default()`; then sync PriceList / ItemPrice from MenuItem.rate values
- `sync_price_list()`: get-or-create a PriceList linked to this menu; delete old ItemPrice rows; create new ones from MenuItem rows
- Meta: `unique_together = [("name", "branch")]`, `ordering = ["name"]`
- Back-office form fields: `name`, `enabled` only (no branch picker / list filter)

##### MenuItem (`menu.MenuItem`)

| Field | Type | Notes |
|---|---|---|
| menu | ForeignKey→Menu, on_delete=CASCADE, related_name="items" | |
| item | ForeignKey→inventory.Item, on_delete=PROTECT, related_name="menu_items" | |
| item_name | CharField, max_length=200 | Denormalized from Item.item_name (synced on save) |
| rate | DecimalField, max_digits=10, decimal_places=2 | Selling price — source of truth for POS display |
| special_dish | BooleanField, default=False | Highlighted on POS |
| disabled | BooleanField, default=False | Disabled items hidden from POS |

**Methods:**
- `__str__` returns `item_name or item.item_code`
- `save()`: auto-set `item_name` from `item.item_name` if blank
- `clean()`: if `rate` is blank/zero and `item.last_purchase_rate` is set, default to `item.last_purchase_rate`
- Meta: `unique_together = [("menu", "item")]`, `ordering = ["item_name"]`

##### PriceList (`menu.PriceList`)

| Field | Type | Notes |
|---|---|---|
| name | CharField, max_length=100, unique | Auto-set to menu name |
| enabled | BooleanField, default=True | |
| selling | BooleanField, default=True | |
| buying | BooleanField, default=False | |
| menu | ForeignKey→Menu, null=True, blank=True, on_delete=SET_NULL, related_name="price_lists" | Back-link to the menu that auto-created this price list |

**Methods:** `__str__` returns `name`. Meta: `ordering = ["name"]`.

##### ItemPrice (`menu.ItemPrice`)

| Field | Type | Notes |
|---|---|---|
| item | ForeignKey→inventory.Item, on_delete=CASCADE, related_name="prices" | |
| price_list | ForeignKey→PriceList, on_delete=CASCADE, related_name="prices" | |
| price_list_rate | DecimalField, max_digits=10, decimal_places=2 | The stored price |
| uom | ForeignKey→inventory.UOM, on_delete=PROTECT, related_name="prices" | Defaults to item.stock_uom |

**Methods:** `__str__` returns `f"{item.item_code}: {price_list_rate}"`. Meta: `unique_together = [("item", "price_list", "uom")]`.

##### ItemAddOn (`menu.ItemAddOn`)

POS add-on relationship — links a parent Item to add-on Items.

| Field | Type | Notes |
|---|---|---|
| parent_item | ForeignKey→inventory.Item, on_delete=CASCADE, related_name="add_ons" | The item that has add-ons |
| add_on_item | ForeignKey→inventory.Item, on_delete=PROTECT, related_name="add_on_for" | The add-on item itself |

**Methods:**
- `__str__` returns `f"{parent_item.item_name} + {add_on_item.item_name}"`
- `clean()`: validate that `add_on_item` is a member of at least one Menu (otherwise its POS price would be unresolved)
- Meta: `unique_together = [("parent_item", "add_on_item")]`

##### ItemVariant (`menu.ItemVariant`)

POS variant relationship — links a parent Item to variant Items (e.g. Quarter/Half/Full).

| Field | Type | Notes |
|---|---|---|
| parent_item | ForeignKey→inventory.Item, on_delete=CASCADE, related_name="pos_variants" | The parent/template item |
| variant_item | ForeignKey→inventory.Item, on_delete=PROTECT, related_name="pos_variant_of" | The variant item |

**Methods:**
- `__str__` returns `f"{parent_item.item_name} → {variant_item.item_name}"`
- `clean()`: validate that `variant_item` is a member of at least one Menu
- Meta: `unique_together = [("parent_item", "variant_item")]`

#### Cross-app migration: add active_menu to Restaurant

The settings app's Restaurant model needs an `active_menu` FK to Menu. This is done via a migration in the menu app:

```python
# menu/migrations/0002_add_active_menu_to_restaurant.py
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ("settings", "0001_initial"),
        ("menu", "0001_initial"),
    ]
    operations = [
        migrations.AddField(
            model_name="restaurant",
            name="active_menu",
            field=models.ForeignKey(
                "menu.Menu",
                on_delete=django.db.models.deletion.SET_NULL,
                null=True,
                blank=True,
                related_name="active_for_restaurants",
            ),
        ),
    ]
```

#### Views & URLs

| URL pattern | View | Purpose |
|---|---|---|
| `/backoffice/menu/` | `menu_dashboard` | Overview with menu count, item count |
| `/backoffice/menu/menus/` | `menu_list` / `menu_create` / `menu_detail` / `menu_update` | Menu CRUD (with inline formset for MenuItems) |
| `/backoffice/menu/items/` | `menu_item_list` / `menu_item_create` / `menu_item_update` | Standalone MenuItem CRUD (optional — mostly managed via Menu inline) |
| `/backoffice/menu/add-ons/` | `add_on_list` / `add_on_create` / `add_on_update` / `add_on_delete` | ItemAddOn CRUD |
| `/backoffice/menu/variants/` | `variant_list` / `variant_create` / `variant_update` / `variant_delete` | ItemVariant CRUD |
| `/backoffice/menu/price-lists/` | `price_list_list` / `price_list_detail` | PriceList read-only views |

#### Tests

| Test file | What it covers |
|---|---|
| `test_menu.py` | CRUD, enabled toggle, sync_price_list creates PriceList + ItemPrice rows |
| `test_menu_item.py` | CRUD, rate default from item.last_purchase_rate, item_name sync, disabled filter, special_dish flag |
| `test_price_list.py` | Auto-creation from Menu, ItemPrice sync, unique constraint |
| `test_item_add_on.py` | CRUD, unique constraint, validation that add_on_item must be in a Menu |
| `test_item_variant.py` | CRUD, unique constraint, validation that variant_item must be in a Menu |
| `test_views.py` | Login required, list/create/update views, HTMX responses |

#### Deviations from reference

| Deviation | Reason |
|---|---|
| No `room_wise_menu` or `order_type_wise_menu` | FEATURES.md #7: single menu for all rooms/order types |
| PriceList/ItemPrice kept but POS reads from MenuItem.rate | Matches URY pattern |
| `department` not on MenuItem | Already on inventory.Item — inherited via FK |
| ItemAddOn/ItemVariant are standalone models, not child tables on Item | Django ORM pattern — cleaner queries than child tables |
| Branch kept in DB but hidden in Phase 1 UI across Menu/Room/Warehouse/Restaurant (auto `Branch.get_default()`); Table & UserRoomAssignment derive branch from room | Single-site restaurant; multi-branch isolation remains available without cashier-facing branch pickers |

---

### 6.4 Payments Core App (Phase 4)

**Status:** complete — 43 tests passing, lint clean (1 pre-existing scratch-script error), migrations applied
**FEATURES.md sections:** A10 (partial — modes and GL mapping only)
**Dependencies:** None (standalone). Promoted ahead of Staff because `OpeningPayment.mode_of_payment`
is a FK to `ModeOfPayment`.
**Key models:** `ModeOfPayment`, `PaymentGLMapping`
**Reference doctypes to consult:** ERPNext Mode of Payment, Mode of Payment Account

#### Reference files consulted

| Reference file | What was extracted |
|---|---|
| `references/erpnext-develop/erpnext/accounts/doctype/mode_of_payment/mode_of_payment.json` | Fields: `mode_of_payment` (name), `type` (Cash/Bank/General/Phone), `enabled` |
| `references/erpnext-develop/erpnext/accounts/doctype/mode_of_payment/mode_of_payment.py` | Empty `Document` class — no validation logic |
| `references/erpnext-develop/erpnext/accounts/doctype/mode_of_payment_account/mode_of_payment_account.json` | Child-table fields: `company`, `default_account` |
| `references/erpnext-develop/erpnext/selling/doctype/pos_profile/pos_profile.json` | How POS Profile lists allowed payment methods per terminal |
| `references/ury-develop/ury/ury_pos/api.py` | How URY resolves `mode_of_payment` against the active POS profile |

#### Decisions

- **Flat master, no tree.** Modes are categorised by a `type` field, not nested under a parent mode.
- **`PaymentGLMapping.default_account` is a CharField, not a Link→Account.** Phase 1 has no
  `LedgerAccount` model — that lives in Phase 9 (reports). We store the account name as a string
  here and migrate to a FK when the chart of accounts is introduced.
- **`company` is a CharField** read from `Restaurant.company` (single-company Phase 1). No
  per-company switcher in Phase 1; refactor in Phase 2.
- **No `is_change` flag.** A mode of payment's ability to dispense physical change is inferred
  from `type == "CASH"`. The Order app (Phase 7) handles change calculation, not here.
- **Simple `enabled` toggle.** Disabled modes are hidden from the opening-balance form on the
  staff app while remaining valid historical references on past opening entries. ERPNext hides
  modes via the POS Profile's `payments` child table; RestPOS has no POS Profile yet, so we keep
  the toggle on the master.

#### Models (2 total)

All models extend `apps.utils.models.BaseModel`.

##### `ModeOfPayment` (`payments.ModeOfPayment`)

| Field | Type | Notes |
|---|---|---|
| `name` | CharField, max_length=50, unique | e.g. "Cash", "Bank Transfer", "Opay Transfer" |
| `type` | CharField, max_length=10, choices: CASH / BANK / GENERAL / PHONE | required — #94 |
| `enabled` | BooleanField, default=True | disabled modes hidden from new opening entries |

**Methods:**
- `__str__` returns `name`
- Meta: `ordering = ["name"]`

**Seed data (migration 0002):** Cash (CASH), Bank Transfer (BANK), Card (BANK), USSD / Mobile Money (PHONE).
The manager can add specific providers (Opay, Moniepoint, FirstBank POS) or disable unused ones.

##### `PaymentGLMapping` (`payments.PaymentGLMapping`)

| Field | Type | Notes |
|---|---|---|
| `mode_of_payment` | ForeignKey→`payments.ModeOfPayment`, on_delete=PROTECT, related_name="gl_mappings" | required |
| `company` | CharField, max_length=200 | defaults from `Restaurant.company`; Phase 1 has one company |
| `default_account` | CharField, max_length=200 | account name as string — Phase 9 will FK to a real `LedgerAccount` |

**Methods:**
- `__str__` returns `f"{mode_of_payment.name} → {default_account}"`
- `clean()`: default `company` from `Restaurant.objects.first().company` if blank
- Meta: `unique_together = [("mode_of_payment", "company")]`, `ordering = ["mode_of_payment__name"]`

#### Views & URLs

Function-based views, `@login_required`, protected by `BackofficeAccessMiddleware` via the
`/backoffice/...` path prefix. HTMX partials return `"<template>.html#<partialdef>"`.

| URL pattern | View | Purpose |
|---|---|---|
| `/backoffice/payments/` | `payments_dashboard` | Overview: mode count, GL mapping count, disabled count |
| `/backoffice/payments/modes/` | `mode_list` | List modes with HTMX partial for rows |
| `/backoffice/payments/modes/create/` | `mode_create` | Create mode |
| `/backoffice/payments/modes/<int:pk>/` | `mode_detail` | View mode + its GL mappings inline |
| `/backoffice/payments/modes/<int:pk>/edit/` | `mode_update` | Update mode |
| `/backoffice/payments/gl-mappings/` | `gl_mapping_list` | List GL mappings |
| `/backoffice/payments/gl-mappings/create/` | `gl_mapping_create` | Create mapping |
| `/backoffice/payments/gl-mappings/<int:pk>/edit/` | `gl_mapping_update` | Edit mapping |
| `/backoffice/payments/gl-mappings/<int:pk>/delete/` | `gl_mapping_delete` | Remove mapping (`@require_POST`) |

#### Templates

| Template | Purpose |
|---|---|
| `templates/backoffice/payments/dashboard.html` | Overview landing page |
| `templates/backoffice/payments/mode_list.html` with `{% partialdef mode-row %}` + `{% partialdef mode-rows %}` | List with HTMX partials |
| `templates/backoffice/payments/mode_form.html` with `{% partialdef form inline %}` | Create/edit mode |
| `templates/backoffice/payments/mode_detail.html` | Show mode + GL mappings inline |
| `templates/backoffice/payments/gl_mapping_list.html` | List mappings with `{% partialdef gl-mapping-row %}` |
| `templates/backoffice/payments/gl_mapping_form.html` | Create/edit mapping |

#### Forms

| Form | Model | Notes |
|---|---|---|
| `ModeOfPaymentForm` | `ModeOfPayment` | Fields: name, type, enabled |
| `PaymentGLMappingForm` | `PaymentGLMapping` | `mode_of_payment` queryset via `active_choices(ModeOfPayment, self.instance.mode_of_payment_id, enabled=True)`; `company` defaulted in `__init__` from `Restaurant.objects.first().company` |

Both extend `apps.utils.forms.StyledModelForm` via a `PaymentsModelForm(StyledModelForm)` base.

#### Admin

```python
@admin.register(ModeOfPayment)
class ModeOfPaymentAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "enabled", "created_at")
    list_filter = ("type", "enabled")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(PaymentGLMapping)
class PaymentGLMappingAdmin(admin.ModelAdmin):
    list_display = ("mode_of_payment", "company", "default_account", "created_at")
    list_filter = ("company",)
    list_select_related = ("mode_of_payment",)
    search_fields = ("mode_of_payment__name", "default_account")
    ordering = ("mode_of_payment__name",)
```

#### Tests

| Test file | What it covers |
|---|---|
| `test_mode_of_payment.py` | CRUD, type choices, `enabled` flag, unique name, seed migration creates 4 defaults |
| `test_payment_gl_mapping.py` | CRUD, `unique_together(mode, company)`, company defaulting from `Restaurant`, PROTECT on mode delete |
| `test_views.py` | Login required, list/create/update/delete, HTMX partial responses, `@require_POST` on delete (GET → 405) |

#### Deviations from reference

| Deviation | Reason |
|---|---|
| `default_account` is CharField, not Link→Account | No `LedgerAccount` model in Phase 1; Phase 9 introduces one and migrates to FK |
| `company` is CharField, not Link→Company | No Company model in Phase 1 — single `Restaurant` singleton per branch with a company name string |
| No per-warehouse or per-branch isolation on modes | Phase 1 is single-branch; modes are shared restaurant-wide |
| No `is_change` flag | Change capability inferred from `type == "CASH"`; only cash modes dispense physical notes |
| Simple `enabled` toggle on mode | ERPNext hides modes via POS Profile's `payments` child table. RestPOS has no POS Profile yet, so the toggle lives on the master. |
| Seed includes "USSD / Mobile Money" (PHONE) | Common in Nigerian restaurant context; matches #94 ("Phone (mobile money / USSD)") |

#### Implementation steps

1. Create the app: `make uv run 'pegasus startapp payments ModeOfPayment PaymentGLMapping'`
2. Write models in `apps/payments/models.py`
3. Write forms in `apps/payments/forms.py`
4. Write views in `apps/payments/views.py`
5. Write URLs in `apps/payments/urls.py`
6. Register in `apps/payments/admin.py`
7. Add `apps.payments` to `INSTALLED_APPS` in `restpos/settings.py` (after `apps.menu`)
8. Include payments URLs in `restpos/urls.py`
9. Write templates in `templates/backoffice/payments/`
10. Create and run migrations: `make migrations && make migrate`
11. Write seed migration `0002_seed_payment_modes.py` — creates Cash, Bank Transfer, Card, USSD
12. Write tests: `apps/payments/tests/`
13. Run tests: `make test ARGS='apps.payments'`
14. Run lint: `make ruff`

---

### 6.5 Staff App (Phase 5)

**Status:** complete — 58 tests passing, lint clean (1 pre-existing scratch-script error), 472 total tests
across the project, migrations applied
**FEATURES.md sections:** A9 (POS session / cashier shift), A17 (role enforcement on shift ops;
the role-group conventions themselves already live in `apps/users` and the settings-app staff list)
**Dependencies:** settings R1 (Branch), payments core (ModeOfPayment)
**Key models:** `POSOpeningEntry`, `OpeningPayment`, `POSClosingEntry`, `ClosingPayment`
**Reference doctypes to consult:** ERPNext POS Opening Entry + Detail, POS Closing Entry + Detail +
Taxes, URY User, Role Permitted, URY hooks for opening/closing validation

#### Reference files consulted

| Reference file | What was extracted |
|---|---|
| `references/erpnext-develop/erpnext/accounts/doctype/pos_opening_entry/pos_opening_entry.json` | Submittable doctype — fields: period_start_date, period_end_date, posting_date, company, pos_profile, user, balance_details, status, amended_from |
| `references/erpnext-develop/erpnext/accounts/doctype/pos_opening_entry/pos_opening_entry.py` | `validate_pos_profile_and_cashier`, `check_open_pos_exists`, `check_user_already_assigned`, `validate_payment_method_account`, submit/cancel logic, `check_poe_is_cancellable` |
| `references/erpnext-develop/erpnext/accounts/doctype/pos_opening_entry_detail/pos_opening_entry_detail.json` | Child table: `mode_of_payment` (Link), `opening_amount` (Currency) |
| `references/erpnext-develop/erpnext/accounts/doctype/pos_closing_entry/pos_closing_entry.json` | Submittable — fields: period dates, posting_date/time, pos_opening_entry (Link), pos_invoices, sales_invoices, taxes, totals, payment_reconciliation, status, amended_from |
| `references/erpnext-develop/erpnext/accounts/doctype/pos_closing_entry/pos_closing_entry.py` | `validate_pos_opening_entry`, `validate_duplicate_pos_invoices`, `validate_pos_invoices`, `on_submit` (consolidates), `on_cancel` (unconsolidates, does NOT reopen opening), `get_invoices` |
| `references/erpnext-develop/erpnext/accounts/doctype/pos_closing_entry_detail/pos_closing_entry_detail.json` | Child table: mode_of_payment, opening_amount, expected_amount, closing_amount, difference |
| `references/erpnext-develop/erpnext/controllers/status_updater.py` (lines 150–162) | Derived `status` rules for both doctypes: opening `Draft→Open→Closed→Cancelled` keyed on `docstatus` + presence of `pos_closing_entry`; closing `Draft→Submitted→Queued/Failed→Cancelled` |
| `references/ury-develop/ury/ury/doctype/ury_user/ury_user.json` | Child table of URY User (user + room) on Branch — single shared session per branch |
| `references/ury-develop/ury/ury/hooks/ury_pos_opening_entry.py` | `set_cashier_room`, `main_pos_open_check` (sub-cashier must wait for main) — **not ported**; RestPOS uses single-session model |
| `references/ury-develop/ury/ury/hooks/ury_pos_closing_entry.py` | `calculate_closing_amount`, `validate_cashier` — **not ported**; single-session model |
| `references/ury-develop/ury/ury_pos/api.py` `getPosProfile` / `posOpening` / `pos_opening_check` | How URY exposes shift state to the POS frontend — pattern for `staff_dashboard` view |
| `references/ury-develop/ury/ury/doctype/sub_pos_closing/sub_pos_closing.json` | Sub-cashier close — **not ported**; single-session model |

#### Decisions

- **Single shared session per branch (FEATURES.md #85).** One Open shift per branch; any permitted
  cashier rings sales on it; orders are attributed to whoever is logged in. No multi-cashier mode,
  no `Sub POS Closing`, no main/sub hierarchy. The session is shared; the shift's `cashier` field
  records who opened it for audit.
- **POSProfile FK deferred to Phase 6.** `POSProfile` is built in Phase 6 (settings R2). In Phase 5
  the shift is identified by `(branch, status="SUBMITTED" AND closing_entry IS NULL)`. Phase 6 adds
  a nullable `pos_profile` FK via a migration.
- **Synchronous close only.** No `QUEUED`/`FAILED` statuses, no Celery task, no `error_message`,
  no Retry button. Phase 5's close-time work is a SQL `SUM` across the shift's `OpeningPayment`
  rows plus the cashier-entered `closing_amount` — milliseconds even for 1,000+ orders. Add async
  only when a future phase introduces heavy close-time write work (e.g. Phase 9 reports writing GL
  entries on close, or a real `Sales Invoice` consolidation).
- **Daily-close enforcement deferred.** The ERPNext `validate_pos_opening_entry` "outdated shift"
  check and URY's `validate_pos_close` 5 AM day boundary live in the Order-app `validate` path
  (Phase 7), not on the opening entry. Mirrors ERPNext's placement in
  `sales_invoice/services/pos.py` and avoids coupling Phase 5 to order-creation concerns.
- **Order FK linkage deferred to Phase 7.** Phase 5 builds the opening/closing shell with totals
  defaulting to 0. Phase 7 (orders) adds `Order.pos_opening_entry` and `Order.pos_closing_entry`
  FKs, and extends `POSClosingEntry.submit()` to sum order payments into `expected_amount`.
- **Derived status via property.** `POSOpeningEntry.is_open` returns `True` iff
  `status == "SUBMITTED" AND closing_entry_id IS NULL`. The "Open" / "Closed" labelling is
  implied by `status` + `closing_entry`, not stored as a separate field.
- **Cancel does NOT reopen the opening entry** (matches ERPNext). Once a closing entry exists,
  the opening entry stays closed. Cancellation of a closing entry is blocked if a new Open shift
  exists for the branch.
- **Manager + Cashier can both open/close.** Whoever is logged in with `has_staff_role` can act.
  Admin can always act. `cashier` field is the user who opened (audit), not a single permitted user.
- **GL-account check on opening balance deferred.** ERPNext requires every `mode_of_payment` in
  the opening balance to have a GL account mapped. RestPOS has no `LedgerAccount` in Phase 1, so
  this check is deferred — the manager ensures each enabled mode has a `PaymentGLMapping` row via
  the payments core CRUD before opening a shift.
- **Round two-decimal precision only.** `opening_amount`, `expected_amount`, `closing_amount`,
  `difference` are all `DecimalField(max_digits=12, decimal_places=2)`. The restaurant deals in
  whole naira (see FEATURES #100 — rounding is a Phase 7 / 9 concern).

#### Models (4 total)

All models extend `apps.utils.models.BaseModel`.

##### `POSOpeningEntry` (`staff.POSOpeningEntry`)

| Field | Type | Notes |
|---|---|---|
| `branch` | ForeignKey→`settings.Branch`, on_delete=PROTECT, related_name="pos_opening_entries" | required; auto-set via `Branch.get_default()` in `save()` if blank |
| `period_start_date` | DateTimeField, default=timezone.now, editable=False | shift start |
| `period_end_date` | DateTimeField, null=True, blank=True, editable=False | set when closing entry submits |
| `posting_date` | DateField, default=timezone.localdate | calendar day of shift |
| `cashier` | ForeignKey→`users.CustomUser`, on_delete=PROTECT, related_name="pos_opening_entries" | the user who opened the shift (audit) |
| `closing_entry` | OneToOneField→`staff.POSClosingEntry`, on_delete=SET_NULL, null=True, blank=True, related_name="opening_entry_ref" | set when shift closes — status driver |
| `status` | CharField, max_length=10, choices: DRAFT / SUBMITTED / CANCELLED, default="DRAFT" | submit/cancel workflow |
| `remarks` | TextField, blank=True | optional notes |
| `cancelled_by` | ForeignKey→`users.CustomUser`, on_delete=SET_NULL, null=True, blank=True, related_name="cancelled_opening_entries" | audit |
| `cancelled_at` | DateTimeField, null=True, blank=True, editable=False | audit |

**Methods:**
- `__str__` returns `f"Opening #{self.pk} — {self.branch.name} {self.posting_date}"`
- `save()`: auto-assign `branch` from `Branch.get_default()` if blank; raise `ValidationError` if
  no default branch exists (caller must create a branch first). Follows the `Warehouse` pattern in
  `apps/inventory/models.py`.
- `clean()`:
  - if no other validation, call `super().clean()` first
  - if `status == "SUBMITTED"` and `closing_entry_id` is None: verify no other submitted
    opening entry with a null closing entry exists for the same branch (one Open shift per branch)
- `is_open` → `@property` returning `self.status == "SUBMITTED" and self.closing_entry_id is None`
- `is_closed` → `@property` returning `self.status == "SUBMITTED" and self.closing_entry_id is not None`
- `submit()`: idempotency guard `if self.status != "DRAFT": return`; set `status = "SUBMITTED"`;
  `self.save(update_fields=["status", "updated_at"])`. No side effects — no SLE creation, no
  revenue posting. The shift is now "Open" and any permitted cashier can ring sales on it (the
  Order-app validate path enforces the "exactly one Open per branch" rule at order-create time).
- `cancel()`: idempotency guard `if self.status != "DRAFT": return`; set `status = "CANCELLED"`,
  `cancelled_at = timezone.now()`; caller is responsible for setting `cancelled_by` (the view
  passes the current user). Cannot cancel a shift that has a `closing_entry` (closed shifts are
  immutable — matches ERPNext). The view raises a `ValidationError` if `closing_entry_id` is not
  None.

**Meta:** `ordering = ["-period_start_date"]`.

##### `OpeningPayment` (`staff.OpeningPayment`) — child table

| Field | Type | Notes |
|---|---|---|
| `opening_entry` | ForeignKey→`POSOpeningEntry`, on_delete=CASCADE, related_name="opening_payments" | required |
| `mode_of_payment` | ForeignKey→`payments.ModeOfPayment`, on_delete=PROTECT, related_name="opening_payments" | required |
| `opening_amount` | DecimalField, max_digits=12, decimal_places=2, default=0 | the float entered by the cashier |

**Methods:**
- `__str__` returns `f"{mode_of_payment.name}: {opening_amount}"`
- Meta: `unique_together = [("opening_entry", "mode_of_payment")]`,
  `ordering = ["mode_of_payment__name"]`

##### `POSClosingEntry` (`staff.POSClosingEntry`)

| Field | Type | Notes |
|---|---|---|
| `branch` | ForeignKey→`settings.Branch`, on_delete=PROTECT, related_name="pos_closing_entries" | denormalized from opening_entry for query efficiency |
| `opening_entry` | OneToOneField→`POSOpeningEntry`, on_delete=PROTECT, related_name="closing_entry_for" | required; validated to be `is_open` in `clean()` |
| `period_start_date` | DateTimeField, editable=False | denormalized from opening_entry |
| `period_end_date` | DateTimeField, default=timezone.now | when the close is being submitted |
| `posting_date` | DateField, default=timezone.localdate | calendar day of close |
| `cashier` | ForeignKey→`users.CustomUser`, on_delete=PROTECT, related_name="pos_closing_entries" | user submitting the close |
| `total_quantity` | DecimalField, max_digits=12, decimal_places=2, default=0, editable=False | Phase 7 backfills from Order totals |
| `net_total` | DecimalField, max_digits=14, decimal_places=2, default=0, editable=False | Phase 7 backfills |
| `total_taxes` | DecimalField, max_digits=14, decimal_places=2, default=0, editable=False | Phase 7 backfills |
| `grand_total` | DecimalField, max_digits=14, decimal_places=2, default=0, editable=False | Phase 7 backfills |
| `total_short_excess` | DecimalField, max_digits=14, decimal_places=2, default=0, editable=False | sum of `difference` across all `ClosingPayment` rows |
| `status` | CharField, max_length=10, choices: DRAFT / SUBMITTED / CANCELLED, default="DRAFT" | |
| `remarks` | TextField, blank=True | |
| `cancelled_by` | ForeignKey→`users.CustomUser`, on_delete=SET_NULL, null=True, blank=True, related_name="cancelled_closing_entries" | audit |
| `cancelled_at` | DateTimeField, null=True, blank=True, editable=False | audit |

**Methods:**
- `__str__` returns `f"Closing #{self.pk} — {self.branch.name} {self.posting_date}"`
- `save()`: if `opening_entry_id` is set, auto-assign `branch`, `period_start_date`, and
  `posting_date` from it. Avoids the user re-entering values the opening already has.
- `clean()`:
  - call `super().clean()` first
  - validate `opening_entry.is_open` is True (cannot close a draft, cancelled, or already-closed
    opening). Use field-keyed `ValidationError({...})` for form binding.
  - validate `self.branch_id == self.opening_entry.branch_id`
- `submit()`: see "Business logic" below.
- `cancel()`: idempotency guard; raise `ValidationError` if a new Open shift exists for this
  branch (caller passes the field-keyed dict). Set `status = "CANCELLED"`, `cancelled_at = now()`.
  **Does NOT reopen the opening entry** — matches ERPNext.

**Meta:** `ordering = ["-period_end_date"]`.

##### `ClosingPayment` (`staff.ClosingPayment`) — child table

| Field | Type | Notes |
|---|---|---|
| `closing_entry` | ForeignKey→`POSClosingEntry`, on_delete=CASCADE, related_name="closing_payments" | required |
| `mode_of_payment` | ForeignKey→`payments.ModeOfPayment`, on_delete=PROTECT, related_name="closing_payments" | required |
| `opening_amount` | DecimalField, max_digits=12, decimal_places=2, default=0, editable=False | denormalized from the matching `OpeningPayment` |
| `expected_amount` | DecimalField, max_digits=12, decimal_places=2, default=0, editable=False | Phase 5: `= opening_amount`. Phase 7: `+ sum of order payments in this method` |
| `closing_amount` | DecimalField, max_digits=12, decimal_places=2, default=0 | the cashier's counted amount — only editable field on the row |
| `difference` | DecimalField, max_digits=12, decimal_places=2, default=0, editable=False | `= closing_amount − expected_amount` |

**Methods:**
- `__str__` returns `f"{mode_of_payment.name}: closing {closing_amount} / expected {expected_amount}"`
- `clean()`: call `super().clean()` first; if `closing_entry_id` and `opening_entry_id` are both
  set, validate `mode_of_payment` exists in `closing_entry.opening_entry.opening_payments` (the
  mode must be one declared at shift-open time).
- Meta: `unique_together = [("closing_entry", "mode_of_payment")]`,
  `ordering = ["mode_of_payment__name"]`

#### Business logic — `POSOpeningEntry.submit()`

```python
def submit(self):
    """Mark the opening entry as submitted (the shift is now Open)."""
    if self.status != "DRAFT":
        return
    self.status = "SUBMITTED"
    self.save(update_fields=["status", "updated_at"])
```

#### Business logic — `POSOpeningEntry.cancel()`

```python
def cancel(self, by_user=None):
    """Cancel a draft or open shift. Cannot cancel a closed shift (closing_entry set)."""
    if self.status != "DRAFT":
        return
    self.status = "CANCELLED"
    self.cancelled_at = timezone.now()
    if by_user is not None:
        self.cancelled_by = by_user
    self.save(update_fields=["status", "cancelled_at", "cancelled_by", "updated_at"])
```

#### Business logic — `POSClosingEntry.submit()`

```python
def submit(self):
    """Compute expected amounts, validate, then mark the opening entry as closed."""
    if self.status != "DRAFT":
        return
    opening_modes = {op.mode_of_payment_id: op for op in self.opening_entry.opening_payments.all()}
    for cp in self.closing_payments.all():
        if cp.mode_of_payment_id not in opening_modes:
            raise ValidationError({
                "mode_of_payment": f"{cp.mode_of_payment} was not declared at shift open.",
            })
        cp.opening_amount = opening_modes[cp.mode_of_payment_id].opening_amount
        cp.expected_amount = cp.opening_amount  # Phase 7 will add: + sum(OrderPayment) for this method
        cp.difference = cp.closing_amount - cp.expected_amount
        cp.save(update_fields=["opening_amount", "expected_amount", "difference", "updated_at"])
    self.total_short_excess = sum((cp.difference for cp in self.closing_payments.all()), Decimal("0"))
    self.status = "SUBMITTED"
    self.save(update_fields=["total_short_excess", "status", "updated_at"])
    # Flip opening entry to Closed
    self.opening_entry.closing_entry = self
    self.opening_entry.period_end_date = self.period_end_date
    self.opening_entry.save(update_fields=["closing_entry", "period_end_date", "updated_at"])
```

#### Business logic — `POSClosingEntry.cancel()`

```python
def cancel(self, by_user=None):
    """Cancel a submitted closing entry. Does NOT reopen the opening entry (matches ERPNext).
    Blocked if a new Open shift exists for this branch — a fresh shift would already
    reference its own opening entry, and unconsolidating an old close mid-shift would
    corrupt the new session's accounting.
    """
    if self.status != "DRAFT":
        return
    # Check no new Open shift for this branch
    new_open_exists = POSOpeningEntry.objects.filter(
        branch=self.branch,
        status="SUBMITTED",
        closing_entry__isnull=True,
    ).exclude(pk=self.opening_entry_id).exists()
    if new_open_exists:
        raise ValidationError({
            "branch": (
                f"Cannot cancel this closing entry — a new shift is open for {self.branch.name}. "
                "Close or cancel the new shift first."
            ),
        })
    self.status = "CANCELLED"
    self.cancelled_at = timezone.now()
    if by_user is not None:
        self.cancelled_by = by_user
    self.save(update_fields=["status", "cancelled_at", "cancelled_by", "updated_at"])
    # Note: opening entry stays Closed (closing_entry_id still set) — matches ERPNext.
```

#### Circular FK handling

`POSOpeningEntry.closing_entry` (`OneToOneField→POSClosingEntry`) and
`POSClosingEntry.opening_entry` (`OneToOneField→POSOpeningEntry`) form a circular dependency.
Django handles this with string references and `related_name` — declare both fields normally and
the migration generates two `AddField` operations in the order Django can resolve (one FK added in
each model's initial migration, the other added in a follow-up migration that depends on the
first). Pattern: define `POSOpeningEntry` first with `closing_entry` as a nullable OneToOneField
using `to="staff.POSClosingEntry"` (string), then define `POSClosingEntry` with
`opening_entry = OneToOneField(POSOpeningEntry, ...)`. Tests assert the bidirectional linkage
with `opening.closing_entry == closing` and `closing.opening_entry == opening`.

#### Views & URLs

Function-based views, `@login_required`, protected by `BackofficeAccessMiddleware` via the
`/backoffice/...` path prefix. Shift-management views also require `request.user.has_staff_role`
(view-level guard returning 302 → `web:pending_approval` if false). Mutating endpoints
(`submit`/`cancel`/`create`/`update`/`delete`) use `@require_POST`.

| URL pattern | View | Purpose |
|---|---|---|
| `/backoffice/staff/` | `staff_dashboard` | Overview: current shift state per branch (Open / Closed / None), recent closes |
| `/backoffice/staff/opening-entries/` | `opening_entry_list` | List with HTMX partial for rows |
| `/backoffice/staff/opening-entries/create/` | `opening_entry_create` | Open a new shift (inline formset for `OpeningPayment` rows) |
| `/backoffice/staff/opening-entries/<int:pk>/` | `opening_entry_detail` | View shift + opening payments + action buttons |
| `/backoffice/staff/opening-entries/<int:pk>/edit/` | `opening_entry_update` | Edit draft shift (no edits after submit) |
| `/backoffice/staff/opening-entries/<int:pk>/submit/` | `opening_entry_submit` | Submit (open the shift) — `@require_POST` |
| `/backoffice/staff/opening-entries/<int:pk>/cancel/` | `opening_entry_cancel` | Cancel draft/open shift — `@require_POST` |
| `/backoffice/staff/closing-entries/` | `closing_entry_list` | List with HTMX partial for rows |
| `/backoffice/staff/closing-entries/create/` | `closing_entry_create` | Start a close (selects the branch's Open opening entry; seeds `ClosingPayment` rows from `OpeningPayment`) |
| `/backoffice/staff/closing-entries/<int:pk>/` | `closing_entry_detail` | View shift close + reconciliation form |
| `/backoffice/staff/closing-entries/<int:pk>/edit/` | `closing_entry_update` | Edit `closing_amount` per payment method (HTMX recompute of `difference` on blur) |
| `/backoffice/staff/closing-entries/<int:pk>/submit/` | `closing_entry_submit` | Submit (close the shift) — `@require_POST` |
| `/backoffice/staff/closing-entries/<int:pk>/cancel/` | `closing_entry_cancel` | Cancel — `@require_POST` |

#### Templates

| Template | Purpose |
|---|---|
| `templates/backoffice/staff/dashboard.html` | Current shift state per branch (Open / Closed / None) + recent closes |
| `templates/backoffice/staff/opening_entry_list.html` with `{% partialdef opening-row %}` + `{% partialdef opening-rows %}` | List with HTMX partials |
| `templates/backoffice/staff/opening_entry_form.html` with `{% partialdef form inline %}` | Create/edit with `OpeningCashFloatForm` (cash-only); renders a no-cash error card if no active CASH-type `ModeOfPayment` exists |
| `templates/backoffice/staff/opening_entry_detail.html` | Show shift + opening payments + Submit/Cancel action buttons |
| `templates/backoffice/staff/closing_entry_list.html` with `{% partialdef closing-row %}` + `{% partialdef closing-rows %}` | List with HTMX partials |
| `templates/backoffice/staff/closing_entry_form.html` | Reconciliation form (one row per `mode_of_payment`; read-only opening/expected/diff; editable closing_amount) |
| `templates/backoffice/staff/closing_entry_detail.html` | Show shift close summary + reconciliation |

#### Forms

| Form | Model | Notes |
|---|---|---|
| `POSOpeningEntryForm` | `POSOpeningEntry` | Fields: `posting_date`, `remarks`. Branch auto-assigned by `save()`. Cashier auto-set in view from `request.user`. |
| `OpeningPaymentForm` | `OpeningPayment` | Fields: `mode_of_payment` (active_choices, `enabled=True`), `opening_amount`. `clean()`: at least one row required; no duplicate modes. |
| `POSClosingEntryForm` | `POSClosingEntry` | Fields: `opening_entry` (filtered to `is_open` entries for the branch). Branch, dates, cashier auto-set in view. |
| `ClosingPaymentForm` | `ClosingPayment` | Fields: `mode_of_payment` (read-only), `opening_amount` (read-only), `expected_amount` (read-only), `closing_amount`, `difference` (read-only). The HTMX `hx-post` on `closing_amount` blur recomputes `difference` server-side. |

Forms extend `apps.utils.forms.StyledModelForm` via a `StaffModelForm(StyledModelForm)` base
(for the closing-entry forms). The opening-entry form is a plain `forms.Form`
(`OpeningCashFloatForm`) that dynamically renders one `DecimalField` per active
CASH-type `ModeOfPayment` — see §6.5 Deviations "Opening-float UI is cash-only".
On submit, `opening_entry_create` / `opening_entry_update` auto-seed
`OpeningPayment` rows for **every** active `ModeOfPayment` (cash modes get the
entered amounts; non-cash modes get `0`), preserving ERPNext's one-row-per-MOP
data model for closing reconciliation. The closing-form seed step (creating one
`ClosingPayment` row per `OpeningPayment` row on the opening) happens in the
`closing_entry_create` view after the parent form is saved.

#### Admin

```python
@admin.register(POSOpeningEntry)
class POSOpeningEntryAdmin(admin.ModelAdmin):
    list_display = ("pk", "branch", "cashier", "posting_date", "period_start_date", "period_end_date", "status", "closing_entry")
    list_filter = ("branch", "status", "posting_date")
    list_select_related = ("branch", "cashier", "closing_entry")
    search_fields = ("pk", "cashier__username", "remarks")
    readonly_fields = ("period_start_date", "period_end_date", "cancelled_at", "created_at", "updated_at")
    date_hierarchy = "posting_date"
    ordering = ("-period_start_date",)


@admin.register(OpeningPayment)
class OpeningPaymentAdmin(admin.ModelAdmin):
    list_display = ("opening_entry", "mode_of_payment", "opening_amount")
    list_filter = ("mode_of_payment",)
    list_select_related = ("opening_entry", "mode_of_payment")
    search_fields = ("opening_entry__pk", "mode_of_payment__name")
    ordering = ("opening_entry__pk", "mode_of_payment__name")


@admin.register(POSClosingEntry)
class POSClosingEntryAdmin(admin.ModelAdmin):
    list_display = ("pk", "branch", "cashier", "opening_entry", "period_end_date", "status", "total_short_excess", "grand_total")
    list_filter = ("branch", "status", "posting_date")
    list_select_related = ("branch", "cashier", "opening_entry")
    search_fields = ("pk", "opening_entry__pk", "remarks")
    readonly_fields = (
        "period_start_date", "total_quantity", "net_total", "total_taxes",
        "grand_total", "total_short_excess", "cancelled_at", "created_at", "updated_at",
    )
    date_hierarchy = "posting_date"
    ordering = ("-period_end_date",)


@admin.register(ClosingPayment)
class ClosingPaymentAdmin(admin.ModelAdmin):
    list_display = ("closing_entry", "mode_of_payment", "opening_amount", "expected_amount", "closing_amount", "difference")
    list_filter = ("mode_of_payment",)
    list_select_related = ("closing_entry", "mode_of_payment")
    search_fields = ("closing_entry__pk", "mode_of_payment__name")
    ordering = ("closing_entry__pk", "mode_of_payment__name")
```

#### Tests

| Test file | What it covers |
|---|---|
| `test_pos_opening_entry.py` | CRUD, `is_open` / `is_closed` properties, submit/cancel idempotency guards, "one Open shift per branch" `clean()` enforcement, branch auto-default in `save()` |
| `test_opening_payment.py` | Child rows, `unique_together(entry, mode)`, PROTECT on mode delete, queryset ordering |
| `test_pos_closing_entry.py` | CRUD, auto-fill from opening on `save()`, `clean()` opening-must-be-Open check, submit flow (computes `expected_amount` = `opening_amount`, sets `difference`, marks opening closed), cancel blocked by new open shift, cancel does NOT reopen opening |
| `test_closing_payment.py` | `difference` recomputed on submit, `clean()` validates mode matches an opening payment, `unique_together(entry, mode)` |
| `test_views.py` | Login required, role enforcement (`has_staff_role`), HTMX partial responses for list rows, `@require_POST` for submit/cancel (GET → 405), reconciliation-form seed step, hidden branch (no branch picker), opening-edit blocked after submit, dashboard reflects current shift state |
| `test_circular_fk.py` | `opening.closing_entry == closing` and `closing.opening_entry == opening` (the bidirectional linkage survives round-trips) |

#### Deviations from reference

| Deviation | Reason |
|---|---|
| No `pos_profile` FK on `POSOpeningEntry` | `POSProfile` is Phase 6 (settings R2). Phase 5 identifies shifts by branch alone for single-site Phase 1. Phase 6 migration adds the nullable FK. |
| No multi-cashier mode, no `Sub POS Closing` | FEATURES.md #85: one shared session per branch, shared across users. URY's main+sub hierarchy is overkill for Phase 1. |
| No `QUEUED`/`FAILED` statuses, no async consolidation, no Celery task, no `error_message`, no Retry button | Phase 5's close-time work is a SQL `SUM` across `OpeningPayment` rows + a cashier-entered `closing_amount` — milliseconds even for 1,000+ orders. Add async only when a future phase introduces heavy close-time write work. |
| No daily-close "outdated shift" / "5 AM day boundary" check | Lives in the Order-app `validate` path (Phase 7), not on the opening entry. Mirrors ERPNext's placement in `sales_invoice/services/pos.py` and avoids coupling Phase 5 to order-creation concerns. |
| No `pos_invoices` / `sales_invoices` child table on `POSClosingEntry` | `Order` is Phase 7. Phase 5's closing entry has the `total_*` summary fields defaulting to 0; Phase 7 backfills them via computation on close. |
| `closing_entry` is a `OneToOneField`, not ERPNext's `Data` field | Django supports the FK cleanly. ERPNext used `Data` because Frappe uses the field's presence as a status driver for the parent opening's `Open→Closed` transition. In Django we set the FK in `closing_entry.submit()`. |
| Cancel of opening entry allowed iff no `closing_entry` exists (simpler than ERPNext's "no unconsolidated invoices" check) | No invoices exist before Phase 7. |
| `cashier` = creating user (audit), not a single permitted user | Single-session per branch means whoever's logged in with a staff role can act; `cashier` is who opened the shift, recorded for audit. |
| Manager + Cashier roles can both open/close | Single-session model — whoever is logged in with `has_staff_role` acts. Admin can always act. |
| GL account validation on opening balance deferred | No `LedgerAccount` model in Phase 1; the manager ensures each enabled `ModeOfPayment` has a `PaymentGLMapping` row via the payments core CRUD before opening a shift. |
| `expected_amount` in Phase 5 = `opening_amount` only | Phase 7 extends `POSClosingEntry.submit()` to add Σ order payments in the same mode. The Phase 5 plan explicitly notes the extension point. |
| `period_start_date` defaults to `timezone.now()` on creation, not on submit | The cashier expects the shift to start when they hit "Open", not when they finished typing the form. Matches ERPNext's `pos_opening_entry.js` `period_start_date: now_datetime()` on form load. |
| **Opening-float form: all-methods with 0 default.** `OpeningFloatForm` renders one `DecimalField` per active `ModeOfPayment` (CASH-type sorted first), every field pre-filled with `0.00` and `required=False`. This is a faithful carbon-copy of ERPNext's Desk JS pre-population (`pos_opening_entry.js` lines 42-54, which adds one row per configured payment method with `opening_amount=0`) and the Frappe docs ("Opening balances for other payment methods (e.g., Card, UPI, Wallet) can be entered if applicable"). The cashier typically only fills the cash drawer count; electronic fields are left at 0 when the bank/POS balance is not accessible at shift-open time, and can be overridden with the actual opening balance when it is. The ERPNext data model is preserved exactly — `OpeningPayment` has one row per configured `ModeOfPayment` so `POSClosingEntry.submit()` (which iterates `entry.opening_payments.all()`) works unchanged. `posting_date` (defaults to today on the model) and `remarks` (blank by default) are no longer exposed in the cashier-facing form. If no active `ModeOfPayment` exists at all, the form renders a no-modes error card and blocks shift open. | (1) Cashier friction: the original ERPNext Desk UI shows an editable table with a mode-of-payment dropdown per row, requiring the cashier to add/remove rows manually. A pre-populated grid with one numeric input per active mode is faster and eliminates the duplicate-mode / missing-mode risk of free-form rows. (2) Field validation (`min_value=0`, `step=0.01`, `inputmode=decimal`) gives mobile-friendly numeric input without needing the custom `OpeningPaymentForm`+`OpeningPaymentFormSet` machinery — the per-row mode is rendered as a display label, not a FK dropdown, because the cashier is filling amounts for pre-determined modes, not choosing which modes to declare. (3) All fields default to 0 and are `required=False` so a POST with no entered amounts doesn't fail form validation but creates fully-reconcilable rows — matches ERPNext's `reqd: 1 + default: "0"` semantics (a row must exist, 0 is a valid amount). |
| **Closing flow: auto-create-or-reuse draft, inline-edit detail page, no manual shift selection.** Both ERPNext Desk (`pos_closing_entry.js` lines 5-9 — `frm.set_query("pos_opening_entry", ...)` filtered to `status="Open", docstatus=1`) and URY's `sub_pos_closing.js` (lines 37-39, same filter + `user=session.user`) make the cashier manually pick which open shift to close from a filtered Link dropdown. RestPOS Phase 1 **does not** — `closing_entry_create` is now a GET-only endpoint that immediately auto-creates (or reuses an existing) DRAFT `POSClosingEntry` for the single Open shift and redirects to its detail page. `select_for_update()` on the open shift serialises concurrent double-clicks on the "Close Shift" button so they cannot create duplicate drafts; a second GET when a DRAFT already exists just redirects to it. The detail page then renders the reconciliation table as an **inline-editable form** (POSTs back to the same detail URL — PRG pattern) for DRAFT entries, and a read-only `Difference` column for SUBMITTED/CANCELLED entries. The "Submit & Close Shift" button is wired to a SweetAlert confirmation dialog (`data-confirm-title` / `data-confirm-body` / `data-confirm-button` attributes — existing pattern used in `opening_entry_detail.html`, `gl_mapping_list.html`, `staff_list.html`) so the cashier must explicitly confirm before the close finalises. The separate `closing_entry_update` view + URL are removed; `closing_entry_form.html` and `closing_entry_reconcile.html` templates are deleted. The "Close Shift" action is available from the staff dashboard (existing), the opening-entry list (new `Close shift` link on `is_open` rows), and the closing-entry list (detail view). | (1) RestPOS Phase 1 enforces "one Open shift per branch" (see `POSOpeningEntry.clean()` + `submit()` re-check inside `select_for_update`), so a dropdown of open shifts is a list-of-one and pure friction. ERPNext/URY require manual selection only because their architecture permits multi-open-shifts per user and multi-cashier per profile — neither applies to Phase 1. (2) Industry consensus for single-shift-per-register POS systems (Lightspeed S-Series, Dynamics 365 Commerce `Tender declaration`→`Close shift`, StoreHub, ConnectPOS) is one-click close against the current shift, no selection step. (3) The auto-reuse-existing-draft guard prevents the double-click-on-`Close-Shift` race and the page-refresh-after-creating-draft race from leaking orphan drafts. (4) Folding the edit form into the detail page (one page instead of two) halves click count and matches the existing `opening_entry_form.html` symmetry. (5) The SweetAlert confirmation on submit honours ERPNext's submit-then-immutable pattern (the closing entry cannot be edited after submit, only cancelled) — the cashier explicitly agrees before the irreversibility kicks in. |
| **Opening flow: inline-edit detail page for DRAFT, no separate edit form.** Symmetric with the closing-flow change. `opening_entry_detail` now accepts POST for DRAFT entries (re-uses `_save_opening_entry` to persist the edited amounts via the same `OpeningFloatForm`), renders the float table as an inline-editable form for DRAFT entries (POST back to the same detail URL — PRG), and a read-only two-column table for SUBMITTED/CANCELLED/Open entries. The separate `opening_entry_update` view + URL are removed; `opening_entry_form.html` is kept ONLY for `opening_entry_create` (the "Open Shift" action on the dashboard creates the initial draft, then redirects to the detail page for editing — same pattern as `closing_entry_create`). The "Submit & Open Shift" button is now wired to a SweetAlert confirmation dialog (symmetry with "Submit & Close Shift"). The legacy `confirm_empty` branch in `opening_entry_submit` is removed because `_save_opening_entry` now always seeds one row per active `ModeOfPayment` — a draft with no rows only exists if no modes are configured, in which case the create form blocks it at the form level. | (1) Symmetry: closing detail already had inline editing; opening detail now matches — both draft pages edit in place, both submitted pages are read-only. (2) Cuts one navigation hop per draft edit (no separate Edit button + form page). (3) SweetAlert confirmation on submit mirrors the closing submit — the cashier explicitly confirms before the irreversible shift-open. (4) The `confirm_empty` path was dead code — removing it eliminates an untestable branch. |
| **Closing reconciliation: clarify `expected_amount` column to the cashier.** A tooltip is rendered on both the closing-detail page and the opening-detail page's closing-reconciliation table explaining that `Expected = Opening + collected sales during the shift (Phase 1 has no order tracking yet, so expected equals opening)`, and `Difference = closing − expected` (negative = short, positive = excess). | Without this, Phase 1 cashiers see `expected = opening` and assume it's a bug (it's not — it's correct for Phase 5's scope; Phase 7's `POSClosingEntry.submit()` extension adds Σ collected sales per method, making `expected ≠ opening` and `difference ≈ 0` for honest shifts). The tooltip makes the Phase 5 / Phase 7 expansion point visible to the user, not just an internal PLAN.md note. |

#### Implementation steps

1. Create the app: `make uv run 'pegasus startapp staff POSOpeningEntry POSClosingEntry OpeningPayment ClosingPayment'`
2. Write models in `apps/staff/models.py` (handle the circular FK with string references)
3. Write forms in `apps/staff/forms.py` (`OpeningFloatForm` — see §6.5 Deviations; `ClosingPaymentForm` for inline detail-page edit)
4. Write views in `apps/staff/views.py` (with `has_staff_role` guard, `@require_POST` for mutating endpoints, HTMX partial returns)
5. Write URLs in `apps/staff/urls.py`
6. Register in `apps/staff/admin.py`
7. Add `apps.staff` to `INSTALLED_APPS` in `restpos/settings.py` (after `apps.payments`)
8. Include staff URLs in `restpos/urls.py`
9. Write templates in `templates/backoffice/staff/`
10. Create and run migrations: `make migrations && make migrate`
11. Write tests: `apps/staff/tests/`
12. Run tests: `make test ARGS='apps.staff'`
13. Run lint: `make ruff`

---

### 6.6 Settings App — Round 2 (Phase 6)

**Status:** complete — 200 tests passing (96 new Phase 6 tests), lint clean, migrations applied
**FEATURES.md sections:** A3 (Production / Kitchen Station Configuration), A4 (POS Profile /
Terminal Configuration), A5 partial (Tax template)
**Dependencies:** menu (ItemGroup, PriceList), inventory (Warehouse, ItemGroup), payments
(ModeOfPayment, PaymentGLMapping), staff (POSOpeningEntry receives `pos_profile` FK via a
migration in this phase)
**Key models:** `POSProfile`, `POSProfileUser`, `POSProfilePayment`, `ProductionUnit`,
`TaxTemplate`, `TaxRate`

#### Reference files consulted

| Reference file | What was extracted |
|---|---|
| `references/erpnext-develop/erpnext/selling/doctype/pos_profile/pos_profile.json` | POS Profile core fields (44 fields across 4 tabs: identity, accounting, POS configurations, more info) |
| `references/erpnext-develop/erpnext/selling/doctype/pos_profile/pos_profile.py` | Validation: `validate_disabled`, `validate_default_profile`, `validate_all_link_fields`, `validate_duplicate_groups`, `validate_payment_methods`, `validate_accounting_dimensions`; lifecycle `on_update`/`on_trash` → `set_defaults` |
| `references/erpnext-develop/erpnext/selling/doctype/pos_profile_user/pos_profile_user.json` | Applicable-users child: `user` (Link→User), `default` (Check) |
| `references/erpnext-develop/erpnext/selling/doctype/pos_payment_method/pos_payment_method.json` | Payment-methods child: `mode_of_payment` (Link), `default` (Check), `allow_in_returns` (Check) |
| `references/erpnext-develop/erpnext/selling/doctype/pos_item_group/pos_item_group.json` | Item-group filter child: `item_group` (Link) |
| `references/erpnext-develop/erpnext/selling/doctype/pos_customer_group/pos_customer_group.json` | Customer-group filter child (studied and dropped — no Customer model in Phase 1) |
| `references/ury-develop/ury/fixtures/custom_field.json` | 38 URY custom fields on POS Profile (verified); 1 on POS Profile User (`custom_main_cashier`); 3 on URY Printer Settings (`custom_kot_print`, `custom_kot_print_format`, `custom_block_takeaway_kot`); 5 on Branch (aggregator block — dropped) |
| `references/ury-develop/ury/ury/doctype/ury_production_unit/ury_production_unit.json` | Production Unit fields: `production` (autoname), `pos_profile`, `branch` (fetch_from), `warehouse` (fetch_from), `item_groups` child, `printer_settings` child, KDS fields (dropped) |
| `references/ury-develop/ury/ury/doctype/ury_production_unit/ury_production_unit.py` | Empty — no validation logic |
| `references/ury-develop/ury/ury/doctype/ury_printer_settings/ury_printer_settings.json` | Printer-settings child: `bill` (Check), `printer` (Link→Network Printer Settings) + 3 URY custom fields |
| `references/ury-develop/ury/ury/doctype/ury_restaurant/ury_restaurant.json` | `default_tax_template` (core Link → Sales Taxes and Charges Template) — URY's restaurant-wide tax default |
| `references/erpnext-develop/erpnext/accounts/doctype/sales_taxes_and_charges_template/sales_taxes_and_charges_template.json` | TaxTemplate fields: `title`, `is_default`, `disabled`, `company`, `tax_category`, `taxes` (Table→Sales Taxes and Charges) |
| `references/erpnext-develop/erpnext/accounts/doctype/sales_taxes_and_charges_template/sales_taxes_and_charges_template.py` | Validation: default exclusivity per company, disabled-not-default, tax_category uniqueness, per-row account/cost_center validation; `autoname` = `f"{title} - {company_abbr}"` |
| `references/erpnext-develop/erpnext/accounts/doctype/sales_taxes_and_charges/sales_taxes_and_charges.json` | TaxRate row: `charge_type`, `rate`, `account_head`, `description`, `cost_center`, `included_in_print_rate`, `row_id` + computed `*_base_*` fields (deferred to Phase 9) |
| `references/erpnext-develop/erpnext/accounts/doctype/pos_opening_entry/pos_opening_entry.json` | `pos_profile` is a required Link on POS Opening Entry (Phase 6 adds nullable FK to RestPOS POSOpeningEntry) |
| `references/ury-develop/ury/ury_pos/api.py` | Fields the POS frontend consumes from POSProfile (§G of research): `branch`, `warehouse`, `company`, `table_attention_time`, `paid_limit`, `custom_enable_discount`, `custom_enable_multiple_cashier`, `custom_edit_order_type`, `custom_enable_kot_reprint`, `printer_settings`, `role_allowed_for_billing`, `payments`, `applicable_for_users`, `custom_daily_pos_close` |
| `references/ury-develop/ury/ury/doctype/aggregator_settings/aggregator_settings.json` | Reviewed and dropped — third-party food-delivery aggregator integration is out of Phase 1 scope |

#### Decisions

- **TaxTemplate attached only to Restaurant.** ERPNext puts the tax template on
  POSProfile (`taxes_and_charges`); URY puts a `default_tax_template` on the
  Restaurant. RestPOS uses only the Restaurant-level attachment — simpler for
  single-site Phase 1 (one restaurant = one tax config). Phase 7 reads
  `restaurant.default_tax_template` at order time. The POSProfile `taxes_and_charges`
  and `tax_category` fields are not ported.

- **Printer config lives on ProductionUnit as string fields for Phase 6.** Phase 8 owns `PrinterConfig`
  as a standalone model. To avoid a cross-phase stub, Phase 6 stores `printer_ip` (CharField),
  `printer_paper_width` (choices), and `printer_cut_mode` (choices) directly on `ProductionUnit`.
  Phase 8 extracts these into a `PrinterConfig` model and migrates. Documented deviation from URY's
  child-table `printer_settings` approach.

- **`POSOpeningEntry.pos_profile` is a nullable FK in Phase 6.** ERPNext requires it (`reqd:1`).
  RestPOS adds it as nullable to avoid breaking existing Phase 5 opening entries. The FK is not
  enforced as NOT NULL until Phase 7 (orders) requires it for order creation. Additive migration —
  no data backfill needed since Phase 5 entries predate POSProfile.

- **Role-permitted children → M2M to `django.contrib.auth.models.Group`.** URY uses Frappe's `Role`
  via `Role Permitted` child tables. RestPOS uses Django's `Group` with named roles ("RestPOS Admin",
  "RestPOS Manager", "RestPOS Cashier" — Phase 5 staff app). The four role-multiselect fields
  (`role_allowed_for_billing`, `role_restricted_for_table_order`, `transfer_role_permissions`,
  `notification_recipients`) become plain M2M to `Group` with no through model (the through adds no
  data beyond the role ref).

- **`POSProfile.applicable_users` uses a through model `POSProfileUser`.** Preserves the per-user
  `is_default` flag (ERPNext enforces one default per user per company) and `is_main_cashier`
  (URY custom — flags the primary cashier for the API's `get_cashier` logic).

- **`POSProfile.payments` uses a through model `POSProfilePayment`.** Preserves `is_default`
  (exactly one default per profile — ERPNext validation) and `allow_in_returns`.

- **`ProductionUnit.branch` and `warehouse` are stored, auto-set from `pos_profile` in `save()`.**
  Matches the RestPOS denormalization pattern (see `Table.branch`, `UserRoomAssignment.branch`).
  Avoids stale data by re-setting on every save. Deviates from URY which uses `fetch_from` display
  fields.

- **`ProductionUnit.item_groups` child table dropped.** FEATURES.md A3 #14 explicitly states RestPOS
  routes tickets by the `department` flag on each item, not by item-group mappings. The URY
  `item_groups` child is redundant for Phase 1.

- **Aggregator Settings, QZ printing, KDS/Mosaic, KOT audio alert — all dropped.** Out of Phase 1
  scope per AGENTS.md.

- **KOT-related config fields modeled on POSProfile now, enforced in Phase 7/8.** `kot_naming_series`,
  `reset_order_number_daily`, `kot_warning_time`, `notify_kot_delay`, `enable_kot_reprint`,
  `reprint_kot_format` — config toggles consumed by the orders/printing apps. Modeling them now
  keeps POSProfile complete; enforcement is deferred to the consuming phase.

- **Accounting fields kept as CharField, enforcement deferred to Phase 9.** `cost_center`,
  `income_account`, `expense_account`, `write_off_account`, `write_off_cost_center`,
  `account_for_change_amount` — stored as strings (account names). Phase 9 introduces `LedgerAccount`
  and migrates to FK. FEATURES #40 says cost center is mandatory — Phase 6 keeps the field optional
  with a documented deviation (no model to FK to yet); Phase 9 enforces mandatory.

- **`currency` defaults to "NGN".** Single-currency Phase 1. `selling_price_list` kept as nullable
  FK to `menu.PriceList` for ERPNext alignment, but Phase 7 resolves pricing from the active menu
  regardless.

- **`customer` and `customer_groups` dropped.** No Customer model in Phase 1 (walk-in customer is a
  default string handled in Phase 7 if needed).

- **`utm_source`, `utm_campaign`, `utm_medium`, `ignore_pricing_rule`, `letter_head`, `tc_name`,
  `select_print_heading` dropped.** Marketing analytics irrelevant to a local restaurant POS / no
  ERPNext pricing-rule engine / ERPNext print cosmetics. `print_format` kept (consumed by URY API;
  Phase 8 defines RestPOS print formats).

#### Models (6 total)

All models extend `apps.utils.models.BaseModel`.

##### `TaxTemplate` (`settings.TaxTemplate`)

| Field | Type | Source | Notes |
|---|---|---|---|
| title | CharField, max_length=100, required | ERPNext `title` | used in display name |
| is_default | BooleanField, default=False | ERPNext `is_default` | one default per company enforced in `clean()` |
| disabled | BooleanField, default=False | ERPNext `disabled` | disabled templates can't be assigned |
| company | CharField, max_length=200, required | ERPNext `company` | defaults from `Restaurant.company` in `clean()`; no Company model in Phase 1 |
| tax_category | CharField, max_length=100, blank=True | ERPNext `tax_category` | Phase 9 migrates to FK; uniqueness enforced in `clean()` |

**Methods:**
- `__str__` returns `title`
- `clean()`: if `is_default` and `disabled`, raise `ValidationError("Disabled template must not be default")`
- `clean()`: if `is_default`, unset `is_default` on other templates with the same `company` (default exclusivity)
- `clean()`: if `tax_category` set, no other non-disabled template in same `company` may share it
- Meta: `ordering = ["title"]`, `unique_together = [("title", "company")]`

##### `TaxRate` (`settings.TaxRate`) — child table

| Field | Type | Source | Notes |
|---|---|---|---|
| tax_template | ForeignKey→TaxTemplate, on_delete=CASCADE, related_name="rates" | ERPNext `taxes` | |
| charge_type | CharField, max_length=30, choices: ACTUAL / ON_NET_TOTAL / ON_PREVIOUS_ROW_AMOUNT / ON_PREVIOUS_ROW_TOTAL / ON_ITEM_QUANTITY, default=ON_NET_TOTAL | ERPNext `charge_type` | |
| rate | DecimalField, max_digits=8, decimal_places=4, default=0 | ERPNext `rate` | percentage for ON_NET_TOTAL |
| account_head | CharField, max_length=200, required | ERPNext `account_head` | account name string; Phase 9 migrates to FK→LedgerAccount |
| description | CharField, max_length=255, required | ERPNext `description` | |
| cost_center | CharField, max_length=200, blank=True | ERPNext `cost_center` | Phase 9 migrates to FK |
| included_in_print_rate | BooleanField, default=False | ERPNext `included_in_print_rate` | |
| row_id | PositiveIntegerField, null=True, blank=True | ERPNext `row_id` | for previous-row charge types |

**Methods:**
- `__str__` returns `f"{charge_type} {rate}% → {account_head}"`
- Meta: `ordering = ["pk"]`

##### `POSProfile` (`settings.POSProfile`)

| Field | Type | Source | Notes |
|---|---|---|---|
| name | CharField, max_length=100, required | ERPNext Prompt naming | e.g. "Main Cashier", "Bar POS" |
| company | CharField, max_length=200, required | ERPNext core | defaults from `Restaurant.company` in `clean()` |
| branch | ForeignKey→settings.Branch, on_delete=PROTECT, related_name="pos_profiles" | URY custom | auto-set via `Branch.get_default()` in `save()` if blank |
| restaurant | ForeignKey→settings.Restaurant, on_delete=PROTECT, null=True, blank=True, related_name="pos_profiles" | URY custom | auto-set from `branch.restaurants.first()` in `save()` if blank |
| warehouse | ForeignKey→inventory.Warehouse, on_delete=PROTECT, related_name="pos_profiles" | ERPNext core | required — default stock deduction warehouse |
| disabled | BooleanField, default=False | ERPNext core | |
| currency | CharField, max_length=3, default="NGN" | ERPNext core | single-currency Phase 1 |
| selling_price_list | ForeignKey→menu.PriceList, on_delete=SET_NULL, null=True, blank=True, related_name="pos_profiles" | ERPNext core | Phase 7 resolves from active menu |
| taxes_and_charges | — | dropped | tax template lives on Restaurant only, not POSProfile |
| tax_category | CharField, max_length=100, blank=True | ERPNext core | Phase 9 |
| cost_center | CharField, max_length=200, blank=True | ERPNext core | Phase 9 migrates to FK; FEATURES #40 mandatory deferred |
| income_account | CharField, max_length=200, blank=True | ERPNext core | Phase 9 |
| expense_account | CharField, max_length=200, blank=True | ERPNext core | Phase 9 |
| write_off_account | CharField, max_length=200, blank=True | ERPNext core | Phase 9 |
| write_off_cost_center | CharField, max_length=200, blank=True | ERPNext core | Phase 9 |
| write_off_limit | DecimalField, max_digits=12, decimal_places=2, default=Decimal("1.00") | ERPNext core | FEATURES #23 |
| account_for_change_amount | CharField, max_length=200, blank=True | ERPNext core | Phase 9 |
| set_grand_total_to_default_mop | BooleanField, default=True | ERPNext core | FEATURES #25 |
| allow_partial_payment | BooleanField, default=False | ERPNext core | |
| apply_discount_on | CharField, max_length=15, choices: GRAND_TOTAL / NET_TOTAL, default=GRAND_TOTAL | ERPNext core | FEATURES #99 |
| enable_discount | BooleanField, default=False | URY `custom_enable_discount` | FEATURES #18 |
| action_on_new_invoice | CharField, max_length=40, choices: ALWAYS_ASK / SAVE_AND_LOAD_NEW / DISCARD_AND_LOAD_NEW, default=ALWAYS_ASK | ERPNext core | FEATURES #24 |
| validate_stock_on_save | BooleanField, default=False | ERPNext core | |
| hide_images | BooleanField, default=False | ERPNext core | FEATURES #22 |
| hide_unavailable_items | BooleanField, default=False | ERPNext core | FEATURES #22 |
| auto_add_item_to_cart | BooleanField, default=False | ERPNext core | FEATURES #21 |
| allow_rate_change | BooleanField, default=False | ERPNext core | FEATURES #18 |
| allow_discount_change | BooleanField, default=False | ERPNext core | FEATURES #18 |
| allow_warehouse_change | BooleanField, default=False | ERPNext core | FEATURES #18 |
| print_receipt_on_order_complete | BooleanField, default=False | ERPNext core | FEATURES #20 |
| view_all_status | BooleanField, default=False | URY `view_all_status` | FEATURES #32 |
| paid_limit | IntegerField, default=20 | URY `paid_limit` | FEATURES #33 |
| edit_order_type | BooleanField, default=False | URY `custom_edit_order_type` | FEATURES #34 |
| remove_items | BooleanField, default=False | URY `remove_items` | FEATURES #35 |
| show_image | BooleanField, default=True | URY `show_image` | POS item cards |
| require_daily_pos_close | BooleanField, default=False | URY `custom_daily_pos_close` | FEATURES #29 |
| table_attention_time | IntegerField, default=0 | URY `table_attention_time` | FEATURES #74 — minutes |
| multiple_cashier | BooleanField, default=False | URY `custom_enable_multiple_cashier` | |
| kot_naming_series | CharField, max_length=50, default="KOT-####" | URY `custom_kot_naming_series` | FEATURES #27; consumed in Phase 7 |
| reset_order_number_daily | BooleanField, default=False | URY `custom_reset_order_number_daily` | FEATURES #30 |
| kot_warning_time | IntegerField, default=15 | URY `custom_kot_warning_time` | FEATURES #74 — minutes |
| notify_kot_delay | BooleanField, default=False | URY `custom_notify_kot_delay` | FEATURES #38 |
| enable_kot_reprint | BooleanField, default=False | URY `custom_enable_kot_reprint` | FEATURES #28 |
| reprint_kot_format | CharField, max_length=100, blank=True | URY `custom_reprint_kot_format` | Phase 8 defines print formats |
| print_format | CharField, max_length=100, blank=True | ERPNext core | Phase 8 defines |
| applicable_users | ManyToManyField→CustomUser, through=POSProfileUser, related_name="pos_profiles", blank=True | ERPNext core child | |
| payments | ManyToManyField→payments.ModeOfPayment, through=POSProfilePayment, related_name="pos_profiles", blank=True | ERPNext core child | |
| item_groups | ManyToManyField→inventory.ItemGroup, related_name="pos_profiles", blank=True | ERPNext core child | empty = all groups visible |
| role_allowed_for_billing | ManyToManyField→Group, related_name="billing_profiles", blank=True | URY `role_allowed_for_billing` | FEATURES #36 |
| role_restricted_for_table_order | ManyToManyField→Group, related_name="table_order_restricted_profiles", blank=True | URY `role_restricted_for_table_order` | FEATURES #37 |
| transfer_role_permissions | ManyToManyField→Group, related_name="transfer_profiles", blank=True | URY `transfer_role_permissions` | FEATURES #59 |
| notification_recipients | ManyToManyField→Group, related_name="delay_notification_profiles", blank=True | URY `custom_recipients` | FEATURES #38 |

**Methods:**
- `__str__` returns `name`
- `save()`: auto-assign `branch` from `Branch.get_default()` if blank; auto-assign `restaurant`
  from `branch.restaurants.first()` if blank
- `clean()`:
  - if `disabled` and an open `POSOpeningEntry` exists for this profile → raise
    `ValidationError("POS Profile cannot be disabled as there are ongoing POS sessions.")`
  - `payments` must be non-empty → raise
    `ValidationError("Payment methods are mandatory. Please add at least one payment method.")`
  - exactly one `POSProfilePayment` row with `is_default=True` → raise
    `ValidationError("Please select exactly one default mode of payment.")`
  - for every `mode_of_payment` in `payments`, a `PaymentGLMapping` must exist for the current
    `company` → raise `ValidationError("Please set default account for mode(s) of payment: {list}")`
  - no duplicate `item_groups` → raise `ValidationError("Duplicate item group found.")`
  - for each `POSProfileUser` with `is_default=True`, no other non-disabled POSProfile in the same
    `company` may have that user as default → raise
    `ValidationError("User {user} already has a default POS Profile in {company}.")`
- Meta: `ordering = ["name"]`, `unique_together = [("name", "branch")]`

##### `POSProfileUser` (`settings.POSProfileUser`) — through model

| Field | Type | Source | Notes |
|---|---|---|---|
| pos_profile | ForeignKey→POSProfile, on_delete=CASCADE, related_name="user_links" | ERPNext `applicable_for_users` | |
| user | ForeignKey→CustomUser, on_delete=PROTECT, related_name="profile_links" | ERPNext core | |
| is_default | BooleanField, default=False | ERPNext core | one default per user per company (enforced in POSProfile.clean) |
| is_main_cashier | BooleanField, default=False | URY `custom_main_cashier` | flags the primary cashier for API `get_cashier` logic |

**Methods:**
- `__str__` returns `f"{user.username} @ {pos_profile.name}"`
- Meta: `unique_together = [("pos_profile", "user")]`, `ordering = ["user__username"]`

##### `POSProfilePayment` (`settings.POSProfilePayment`) — through model

| Field | Type | Source | Notes |
|---|---|---|---|
| pos_profile | ForeignKey→POSProfile, on_delete=CASCADE, related_name="payment_links" | ERPNext `payments` | |
| mode_of_payment | ForeignKey→payments.ModeOfPayment, on_delete=PROTECT, related_name="profile_links" | ERPNext core | |
| is_default | BooleanField, default=False | ERPNext core | exactly one default per profile (enforced in POSProfile.clean) |
| allow_in_returns | BooleanField, default=False | ERPNext core | |

**Methods:**
- `__str__` returns `f"{mode_of_payment.name} @ {pos_profile.name}"`
- Meta: `unique_together = [("pos_profile", "mode_of_payment")]`,
  `ordering = ["mode_of_payment__name"]`

##### `ProductionUnit` (`settings.ProductionUnit`)

| Field | Type | Source | Notes |
|---|---|---|---|
| name | CharField, max_length=100, required | URY `production` (autoname source) | e.g. "Kitchen", "Bar" |
| pos_profile | ForeignKey→POSProfile, on_delete=PROTECT, null=True, blank=True, related_name="production_units" | URY core | nullable for RestPOS flexibility (unit can exist without a profile in Phase 1) |
| branch | ForeignKey→settings.Branch, on_delete=PROTECT, related_name="production_units" | URY `fetch_from pos_profile.branch` | stored (denormalized); auto-set from `pos_profile.branch` or `Branch.get_default()` in `save()` |
| warehouse | ForeignKey→inventory.Warehouse, on_delete=PROTECT, related_name="production_units" | URY `fetch_from pos_profile.warehouse` | stored (denormalized); auto-set from `pos_profile.warehouse` in `save()` if blank |
| department | CharField, max_length=10, choices: FOOD / DRINKS, required | RestPOS-specific | drives ticket routing per FEATURES #14 |
| block_takeaway_kot | BooleanField, default=False | URY `custom_block_takeaway_kot` (on printer settings) | FEATURES #15 — suppresses ticket for takeaway orders |
| printer_ip | CharField, max_length=50, blank=True | RestPOS-specific (replaces URY `printer_settings` child) | LAN printer static IP; Phase 8 migrates to FK→PrinterConfig |
| printer_paper_width | CharField, max_length=10, choices: WIDTH_58MM / WIDTH_80MM, default=WIDTH_80MM | RestPOS-specific | ESC/POS paper width |
| printer_cut_mode | CharField, max_length=15, choices: FULL_CUT / PARTIAL_CUT / NO_CUT, default=FULL_CUT | RestPOS-specific | ESC/POS cut mode |

**Methods:**
- `__str__` returns `name`
- `save()`: auto-assign `branch` from `pos_profile.branch` if blank, else `Branch.get_default()`;
  auto-assign `warehouse` from `pos_profile.warehouse` if blank
- `clean()`: if `pos_profile` is set, validate `self.branch_id == self.pos_profile.branch_id`
- Meta: `ordering = ["name"]`, `unique_together = [("name", "branch")]`

**Dropped from URY:**
- `item_groups` child table (RestPOS routes by department, not item groups)
- `enable_order_type_wise_display_on_mosaic` (KDS/Mosaic out of scope)
- `order_type` child table (KDS out of scope)
- `printer_settings` child table (folded into `printer_*` fields; Phase 8 may extract)

#### Cross-app migration: add `pos_profile` FK to `POSOpeningEntry`

Phase 5 deferred the `pos_profile` FK on `POSOpeningEntry` (it lives in `apps.staff`). Phase 6 adds
it via a migration in `apps.staff` that depends on the new `apps.settings` migration creating
`POSProfile`. `makemigrations` handles the cross-app dependency automatically. The migration is
additive (`AddField nullable`) — no data backfill needed since Phase 5 entries predate POSProfile.
Do NOT enforce NOT NULL in Phase 6; Phase 7 may enforce when orders require a profile.

```python
# apps/staff/migrations/000X_posopeningentry_pos_profile.py
# Generated by makemigrations — do NOT hand-write the AddField.
# Dependencies: ("settings", "0003_posprofile_..."), ("staff", "<latest>")
operations = [
    migrations.AddField(
        model_name="posopeningentry",
        name="pos_profile",
        field=models.ForeignKey(
            "settings.POSProfile",
            on_delete=models.PROTECT,
            null=True,
            blank=True,
            related_name="opening_entries",
        ),
    ),
]
```

#### Business logic — `POSProfile.clean()`

```python
def clean(self):
    super().clean()
    if self.disabled and self.pk:
        open_exists = POSOpeningEntry.objects.filter(
            pos_profile=self, status="SUBMITTED", closing_entry__isnull=True
        ).exists()
        if open_exists:
            raise ValidationError("POS Profile cannot be disabled as there are ongoing POS sessions.")
    if not self.payment_links.exists():
        raise ValidationError("Payment methods are mandatory. Please add at least one payment method.")
    defaults = self.payment_links.filter(is_default=True)
    if defaults.count() != 1:
        raise ValidationError("Please select exactly one default mode of payment.")
    modes_without_gl = []
    for link in self.payment_links.all():
        if not PaymentGLMapping.objects.filter(
            mode_of_payment=link.mode_of_payment, company=self.company
        ).exists():
            modes_without_gl.append(link.mode_of_payment.name)
    if modes_without_gl:
        raise ValidationError(
            f"Please set default account for mode(s) of payment: {', '.join(modes_without_gl)}"
        )
    seen = set()
    for ig in self.item_groups.all():
        if ig.pk in seen:
            raise ValidationError("Duplicate item group found.")
        seen.add(ig.pk)
    for link in self.user_links.filter(is_default=True):
        other = POSProfileUser.objects.filter(
            user=link.user, is_default=True,
            pos_profile__company=self.company, pos_profile__disabled=False,
        ).exclude(pos_profile=self).exists()
        if other:
            raise ValidationError(
                f"User {link.user.username} already has a default POS Profile in {self.company}."
            )
```

#### Views & URLs

Function-based views, `@login_required`, protected by `BackofficeAccessMiddleware`. Mutating
endpoints (create/edit/delete) require `request.user.is_manager or request.user.is_admin` (view-level
guard returning 302 → `web:pending_approval` if false). Delete endpoints use `@require_POST`.

| URL pattern | View | Purpose |
|---|---|---|
| `/backoffice/settings/pos-profiles/` | `pos_profile_list` | List POS profiles (HTMX partial for rows) |
| `/backoffice/settings/pos-profiles/create/` | `pos_profile_create` | Create profile (inline formsets for users, payments) |
| `/backoffice/settings/pos-profiles/<int:pk>/` | `pos_profile_detail` | View profile + tabs |
| `/backoffice/settings/pos-profiles/<int:pk>/edit/` | `pos_profile_update` | Update profile |
| `/backoffice/settings/pos-profiles/<int:pk>/delete/` | `pos_profile_delete` | Delete profile — `@require_POST` (blocked if open shifts exist) |
| `/backoffice/settings/production-units/` | `production_unit_list` | List units (filterable by branch/department) |
| `/backoffice/settings/production-units/create/` | `production_unit_create` | Create unit |
| `/backoffice/settings/production-units/<int:pk>/` | `production_unit_detail` | View/edit unit |
| `/backoffice/settings/production-units/<int:pk>/edit/` | `production_unit_update` | Update unit |
| `/backoffice/settings/production-units/<int:pk>/delete/` | `production_unit_delete` | Delete unit — `@require_POST` |
| `/backoffice/settings/tax-templates/` | `tax_template_list` | List templates |
| `/backoffice/settings/tax-templates/create/` | `tax_template_create` | Create template (inline formset for rates) |
| `/backoffice/settings/tax-templates/<int:pk>/` | `tax_template_detail` | View template |
| `/backoffice/settings/tax-templates/<int:pk>/edit/` | `tax_template_update` | Update template |
| `/backoffice/settings/tax-templates/<int:pk>/delete/` | `tax_template_delete` | Delete template — `@require_POST` |

#### Templates

| Template | Purpose |
|---|---|
| `templates/backoffice/settings/pos_profile_list.html` | List with `{% partialdef row %}` |
| `templates/backoffice/settings/pos_profile_form.html` | Create/edit with inline formsets for users, payments; M2M widgets for groups/item_groups |
| `templates/backoffice/settings/pos_profile_detail.html` | Tabs: identity, payments, permissions, KOT, print |
| `templates/backoffice/settings/production_unit_list.html` | List with department filter |
| `templates/backoffice/settings/production_unit_form.html` | Create/edit |
| `templates/backoffice/settings/production_unit_detail.html` | View unit + printer config |
| `templates/backoffice/settings/tax_template_list.html` | List |
| `templates/backoffice/settings/tax_template_form.html` | Create/edit with inline formset for rates |
| `templates/backoffice/settings/tax_template_detail.html` | View template + rates |

#### Forms

| Form | Model | Notes |
|---|---|---|
| `POSProfileForm` | `POSProfile` | Excludes `company` (auto from Restaurant), `branch` (auto from `Branch.get_default()`). Inline formsets for `POSProfileUser` and `POSProfilePayment`. M2M widgets for `item_groups`, `role_*` groups. |
| `POSProfileUserForm` | `POSProfileUser` | Fields: `user`, `is_default`, `is_main_cashier` |
| `POSProfilePaymentForm` | `POSProfilePayment` | `mode_of_payment` queryset via `active_choices(ModeOfPayment, ..., enabled=True)`; fields: `is_default`, `allow_in_returns` |
| `ProductionUnitForm` | `ProductionUnit` | `pos_profile` queryset via `active_choices(POSProfile, ..., disabled=False)`. Branch/warehouse auto-set on save. |
| `TaxTemplateForm` | `TaxTemplate` | Fields: `title`, `is_default`, `disabled`, `tax_category`. `company` auto-defaulted in `__init__`. Inline formset for `TaxRate`. |
| `TaxRateForm` | `TaxRate` | Fields: `charge_type`, `rate`, `account_head`, `description`, `cost_center`, `included_in_print_rate`, `row_id` |

Forms extend `apps.utils.forms.StyledModelForm` via the existing `SettingsModelForm` base.

#### Admin

Register all 6 models with `list_display`, `list_filter`, `search_fields`, `list_select_related`.
`POSProfileAdmin` shows key toggles in list. `ProductionUnitAdmin` filters by department.
`TaxTemplateAdmin` filters by company, shows `is_default`. `POSProfileUserAdmin` and
`POSProfilePaymentAdmin` show the parent profile and the linked user/mode.

#### Tests

| Test file | What it covers |
|---|---|
| `test_tax_template.py` | CRUD, default exclusivity per company, disabled-not-default, tax_category uniqueness, TaxRate child CRUD, PROTECT on template delete, `unique_together(title, company)` |
| `test_pos_profile.py` | CRUD, branch auto-default, restaurant auto-default, `clean()` validation (disabled-with-open-shift, payments non-empty, one default payment, GL mapping check, duplicate item groups, default-per-user), `unique_together(name, branch)` |
| `test_pos_profile_user.py` | Through-model CRUD, `is_default` uniqueness per user per company, `is_main_cashier` flag, PROTECT on user delete, `unique_together(profile, user)` |
| `test_pos_profile_payment.py` | Through-model CRUD, `is_default` exactly-one validation, `allow_in_returns`, PROTECT on mode delete, `unique_together(profile, mode)` |
| `test_production_unit.py` | CRUD, department choices, branch/warehouse auto-set from `pos_profile`, `block_takeaway_kot` flag, `printer_ip`/`printer_paper_width`/`printer_cut_mode` fields, `unique_together(name, branch)` |
| `test_pos_opening_entry_pos_profile_fk.py` | The Phase 6 migration adds nullable `pos_profile` FK; existing opening entries still work without one; new entries can reference a profile |
| `test_views.py` | Login required, manager-only on mutating endpoints, HTMX partial responses, `@require_POST` on delete (GET → 405), list filtering (department, branch) |

#### Deviations from reference

| Deviation | Reason |
|---|---|
| TaxTemplate attached to Restaurant only (not POSProfile) | ERPNext = per-profile; URY = per-restaurant. RestPOS uses restaurant-only — simpler for single-site Phase 1. POSProfile `taxes_and_charges` and `tax_category` dropped. |
| Printer config as string fields on ProductionUnit (not child table) | Phase 8 owns PrinterConfig model; storing strings now avoids a cross-phase stub. Phase 8 migrates. |
| `POSOpeningEntry.pos_profile` nullable (not required) | Phase 5 entries predate POSProfile. ERPNext requires it; Phase 7 may enforce NOT NULL. |
| Role-permitted children → M2M to `Group` (not child table to Frappe `Role`) | RestPOS uses Django `Group` with named roles, not Frappe Role. M2M is cleaner than child tables. |
| `POSProfileUser` and `POSProfilePayment` as through models (not child tables) | Django M2M-through pattern; preserves per-row flags (`is_default`, `is_main_cashier`, `allow_in_returns`). `POSProfileUser` dropped in single-profile refactor — Phase 2 re-introduces when multi-profile/club operations are needed. |
| POSProfile limited to one per Restaurant | ERPNext/URY allow multiple profiles per branch (multi-terminal configs). RestPOS Phase 1 is single-site — one POS terminal = one profile. Singleton enforced via `unique_together`. POS profile UI is a settings page, not a list/create/detail CRUD. |
| `ProductionUnit.branch`/`warehouse` stored (not `fetch_from` display) | RestPOS denormalization pattern (matches `Table.branch`); auto-set in `save()`. |
| `item_groups` child on ProductionUnit dropped | RestPOS routes by department flag, not item-group mappings (FEATURES #14). |
| Aggregator Settings, QZ printing, KDS/Mosaic, KOT audio alert dropped | Out of Phase 1 scope per AGENTS.md. |
| `customer`, `customer_groups`, `utm_*`, `ignore_pricing_rule`, `letter_head`, `tc_name`, `select_print_heading` dropped | No Customer model in Phase 1 / irrelevant to local restaurant POS / ERPNext print cosmetics. |
| Accounting fields (`cost_center`, `income_account`, etc.) as CharField, optional | Phase 9 introduces `LedgerAccount` and migrates to FK; FEATURES #40 mandatory deferred. |
| `currency` hardcoded to "NGN" default | Single-currency Phase 1. |
| `selling_price_list` kept but Phase 7 ignores it | ERPNext alignment; RestPOS resolves pricing from active menu. |
| `restaurant` field on POSProfile auto-set from branch | URY has it as user-selected; RestPOS single-site auto-derives. |
| KOT config fields modeled now, enforced in Phase 7/8 | Config toggles consumed by orders/printing apps; modeling now keeps POSProfile complete. |

#### Implementation steps

1. Write models in `apps/settings/models.py` (`TaxTemplate`, `TaxRate`, `POSProfile`,
   `POSProfileUser`, `POSProfilePayment`, `ProductionUnit`)
2. Write forms in `apps/settings/forms.py` (with inline formsets for through models and `TaxRate`)
3. Write views in `apps/settings/views.py` (manager-only mutating endpoints; `@require_POST` on delete)
4. Add URL patterns in `apps/settings/urls.py`
5. Register all 6 models in `apps/settings/admin.py`
6. Create and run migrations: `make migrations && make migrate` (`apps.settings` gets new models;
   `apps.staff` gets `pos_profile` FK — `makemigrations` handles cross-app deps automatically).
   Review the generated `apps.staff` migration to confirm it depends on the new `apps.settings` one.
7. Optional: write a seed migration for a default tax template ("Nigerian VAT 7.5%" with one
   `TaxRate` row: `charge_type=ON_NET_TOTAL`, `rate=7.5`, `account_head="VAT Payable"`)
8. Write templates in `templates/backoffice/settings/`
9. Write tests: `apps/settings/tests/`
10. Run tests: `make test ARGS='apps.settings'`
11. Run lint: `make ruff`
12. Update §3 status table: Phase 6 → `complete`; Phase 7 → `planned` or `not started` (depending
    on whether §6.7 plan exists)

---

### 6.7 Orders App (Phase 7)

**Status:** not started — detailed plan to be written after settings R2 is complete.

**FEATURES.md sections:** A6, A7, A18
**Dependencies:** settings (R1+R2), menu, staff, payments (ModeOfPayment on each payment row)
**Key models:** Order, OrderItem, KOT, KOTItem, RefundEntry, RefundPaymentEntry, RefundStockEntry
**Reference doctypes to consult:** ERPNext POS Invoice, POS Invoice Item, URY Order, URY Order
Item, URY KOT, URY KOT Items, URY hooks for order/KOT/invoice events, URY POS API

> **POS-screen shift UI is a Phase 7 deliverable.** Per user decision (Phase 5 follow-up),
> Phase 7 builds the actual POS screen, which checks for an open shift on load and shows
> an inline "Open Shift" form (opening float per mode) if none is open. The order screen
> will have a "Close Shift" button that walks the cashier through reconciliation. The
> backoffice Staff app (Phase 5) remains the manager audit/reconciliation surface.
> This is a documented deviation from URY, which puts shift open/close entirely in the
> backoffice and gates the POS screen with a "Switch to Desk" blocker.

---

### 6.8 Printing App (Phase 8)

**Status:** not started — detailed plan to be written after orders is complete.

**FEATURES.md sections:** A8
**Dependencies:** orders (ticket data to print)
**Key models:** PrintJob, PrinterConfig
**Reference doctypes to consult:** URY Printer Settings, Network Printer Settings, URY print hooks

---

### 6.9 Reports App (Phase 9)

**Status:** not started — detailed plan to be written after printing is complete.

**FEATURES.md sections:** A14, A15, A16
**Dependencies:** all apps
**Key models:** DailyP&L (or query-based — TBD during planning)
**Reference doctypes to consult:** URY Daily P&L, URY P&L doctypes, ERPNext Sales Invoice reports,
Stock Ledger reports

---

### 6.10 Refunds Completion (Phase 10)

**Status:** not started — detailed plan to be written after reports is complete.

**FEATURES.md sections:** A18
**Dependencies:** orders, payments, inventory
**Key models:** RefundEntry, RefundPaymentEntry, RefundStockEntry (may be part of orders app)
**Reference doctypes to consult:** ERPNext Payment Entry (reversal), Stock Ledger Entry (positive)

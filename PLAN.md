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
                                      settings R2 → orders → printing → reports
                         payments core ↗
                                                                    refunds (cross-app)
```

**Build order reasoning:**
- `settings R1` first — every other app references branches, rooms, and tables
- `inventory` before `menu` — menu items reference the Item master
- `menu` before `orders` — orders contain menu items
- `staff` and `payments` can be built in either order (no mutual dependency)
- `settings R2` needs menu (ItemGroup), inventory (Warehouse), and payments (ModeOfPayment)
- `orders` is the central app — needs settings, menu, and staff
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
| 4 | staff | A9, A17 | POSOpeningEntry, POSClosingEntry, Role definitions | settings R1 | not started |
| 5 | payments core | A10 (partial) | ModeOfPayment, PaymentGLMapping | None (standalone) | not started |
| 6 | settings R2 | A3, A4 | POSProfile, ProductionUnit, TaxTemplate | menu, inventory, payments | not started |
| 7 | orders | A6, A7, A18 | Order, OrderItem, KOT, Ticket, RefundOrder, RefundPaymentEntry | settings (R1+R2), menu, staff | not started |
| 8 | printing | A8 | PrintAgent client, ESC/POS formatter, PrinterConfig | orders | not started |
| 9 | reports | A14, A15, A16 | DailyP&L, SalesReport, StockReport, DepartmentalReport | all apps | not started |
| 10 | refunds | A18 | Refund flow completion (reversal entries, stock restoration) | orders, payments, inventory | not started |

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

### staff (Phase 4)

**Scope:** Two custom roles (Manager, Cashier), role-based permissions per model, POS
opening entries (shift start with float), POS closing entries (shift end with reconciliation),
cashier session validation (one open session per branch, shared across users), daily close
enforcement.

**Key models:** POSOpeningEntry, POSClosingEntry, OpeningPayment, ClosingPayment

**Key reference doctypes:** ERPNext POS Opening Entry, POS Closing Entry, URY User, Role Permitted,
URY hooks for opening/closing validation

### payments core (Phase 5)

**Scope:** Payment modes (Cash, Bank, General, Phone), GL account mapping per company, change
calculation, outstanding amount tracking, additional discounts, rounded total, auto-fill
remaining balance, write-off config.

**Key models:** ModeOfPayment, PaymentGLMapping

**Key reference doctypes:** ERPNext Mode of Payment, POS Payment Method

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

### 6.4 Staff App (Phase 4)

**Status:** not started — detailed plan to be written after menu is complete.

**FEATURES.md sections:** A9, A17
**Dependencies:** settings R1 (POSOpeningEntry references Branch, POSProfile)
**Key models:** POSOpeningEntry, POSClosingEntry, OpeningPayment, ClosingPayment
**Reference doctypes to consult:** ERPNext POS Opening Entry, POS Closing Entry, URY User, Role
Permitted, URY hooks for opening/closing validation

---

### 6.5 Payments Core App (Phase 5)

**Status:** not started — detailed plan to be written after staff is complete.

**FEATURES.md sections:** A10 (partial — modes and GL mapping only)
**Dependencies:** None (standalone — can be built in parallel with staff)
**Key models:** ModeOfPayment, PaymentGLMapping
**Reference doctypes to consult:** ERPNext Mode of Payment, POS Payment Method

---

### 6.6 Settings App — Round 2 (Phase 6)

**Status:** not started — detailed plan to be written after payments core is complete.

**FEATURES.md sections:** A3, A4, A5 (partial)
**Dependencies:** menu (ItemGroup), inventory (Warehouse), payments (ModeOfPayment)
**Key models:** POSProfile, ProductionUnit, TaxTemplate
**Reference doctypes to consult:** ERPNext POS Profile (+ 38 URY custom fields), URY Production
Unit, URY Printer Settings, Aggregator Settings

---

### 6.7 Orders App (Phase 7)

**Status:** not started — detailed plan to be written after settings R2 is complete.

**FEATURES.md sections:** A6, A7, A18
**Dependencies:** settings (R1+R2), menu, staff
**Key models:** Order, OrderItem, KOT, KOTItem, RefundEntry, RefundPaymentEntry, RefundStockEntry
**Reference doctypes to consult:** ERPNext POS Invoice, POS Invoice Item, URY Order, URY Order
Item, URY KOT, URY KOT Items, URY hooks for order/KOT/invoice events, URY POS API

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

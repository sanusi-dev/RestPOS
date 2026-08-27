# Backoffice Workflow

## Access Model

Requests under `/backoffice/` are redirected to the POS unless the user has `has_backoffice_access`, which is true for superusers, RestPOS Admin, or RestPOS Manager. Most backoffice views add only `@login_required`; the middleware supplies the route gate. Explicit manager checks exist for order cancellation/return and settings mutations. Superuser is required for staff role assignment/removal.

## Main Surfaces

| Surface | URL include | Main operations |
|---|---|---|
| Dashboard | `apps.web.urls` | links to modules and setup |
| Settings | `apps.settings.urls` | Restaurant, staff roles, ProductionUnit |
| Inventory | `apps.inventory.urls` | masters, stock documents, stock reports |
| Menu | `apps.menu.urls` | menus, lines, add-ons, variants |
| Payments | `apps.payments.urls` | payment modes and GL mappings |
| Staff | `apps.staff.urls` | opening/closing documents |
| Orders | `apps.orders.urls` | order register, KOT register, cancel, return |
| Accounting | `apps.accounting.urls` | chart of accounts, journal entries, GL entries, fiscal years, supplier payables |
| Reports | `apps.reports.urls` | Daily P&L register, draft/submit/cancel/amend, P&L settings |

## Accounting Operations

All accounting pages are manager/admin-only (the view gate raises 403 directly, in addition to the middleware route gate). The chart of accounts is a tree page with a create/edit form per account; the account form enforces group/leaf and root-type rules via `LedgerAccount.clean()`. Journal entries use a prefixed inline formset of account rows (HTMX row add/remove endpoints that rebuild the posted formset and re-render the accounts partial, per the inventory formset pattern); an empty formset is rejected. Drafts are edited and submitted from the detail page, where submit/cancel/amend are confirmation-aware POSTs. `JournalEntry.submit()` posts balanced rows to the GL; `cancel()` posts reversals; `amend()` copies a cancelled entry into a new draft (one amendment per cancelled entry). GL entries are read-only with account/voucher-type/cancelled filters. Fiscal years are simple CRUD pages. All accounting models are registered in Django admin (`accounting/admin.py`); `GLEntry` and `JournalEntryAccount` are fully read-only there, and journal entries cannot be deleted from admin.

## Daily P&L Operations

All reports pages are manager/admin-only (view 403 plus the middleware route gate). P&L settings hold the business-day start hour, electricity rate, depreciation, cash-variance toggle, material catalog, and recurring expense templates. Creating a Daily P&L saves a draft for one business date (one draft / one submitted per date). The draft form accepts meter readings, material quantities, ad-hoc expenses, and an optional employee-cost override; HTMX "Refresh preview" saves the draft and returns the three-column statement partial. Submit freezes lines and totals inside one atomic block and does not post GL. Cancel leaves the snapshot on file; Amend copies inputs into a new draft that recomputes.

## Inventory Operations

Create views save a parent plus inline formset in an atomic block. HTMX endpoints add/remove formset rows by rebuilding posted data and returning the inline partial. Submit and cancel endpoints call inventory services and redirect to detail with validation messages.

## Menu and Product Operations

Menu and item forms save directly after validation. Model `clean()` enforces cross-app sellability and warehouse rules when it is invoked by forms. A direct `.save()` does not automatically call `full_clean()`, so model validation is most reliable through forms or explicit service validation.

## Order Operations

The order register filters by invoice/customer/order number, status, and order type. Detail prefetches lines, payments, and tickets. Backoffice cancellation requires manager/admin/superuser and calls `cancel_sent_order()` (sent drafts only; unsent drafts are deleted via `order_delete`). Return creation requires the same roles and calls `make_return()`; the negative draft can be edited (qty, drop line, wastage) then submitted through `order_return_submit` → `submit_return()`, which restores drink stock and writes proportional refund rows.

## Settings and Staff

Restaurant and ProductionUnit changes are manager/admin-only at view level. Restaurant validation blocks unsafe warehouse changes when reserved orders or draft stock documents exist. Staff role buttons use HTMX row replacement, but the role value is not validated before removing existing role groups; an unknown role can strip roles. This is documented as a risk, not changed here.

## Reporting Surfaces

`apps.reports` owns the Daily P&L document (Phase 7). Sales reports, trial balance, and the formal GL P&L remain Phase 8.

Current aggregates elsewhere:

- order dashboard: today count, paid count, cancelled count, revenue, recent orders, pending tickets;
- inventory dashboard: catalog, stock, and purchasing navigation with item and UOM counts;
- stock ledger and balance filtered lists;
- staff closing totals and per-mode variance;
- POS history query with date/status/payment/order-type filters.

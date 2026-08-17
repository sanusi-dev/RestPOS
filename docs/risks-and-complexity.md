# Risks and Complexity

This is an inventory of difficult or incomplete areas for future maintenance. It intentionally does not refactor them.

## Highest-Risk Coupling

- `apps/orders/services.py` is the integration hub for orders, inventory, menu, payment master, settings, staff, tickets, audit, and printing.
- `apps/orders/views_pos.py` is a large request coordinator that builds every POS surface and calls staff/order services directly.
- `apps/staff.services` depends on order and payment row semantics to calculate drawer totals.
- `Restaurant.clean()` reaches into orders, inventory, and production units to guard configuration changes.
- Inventory model validation reaches into settings and menu, creating bidirectional domain coupling.

## Lifecycle and Integrity Risks

- `StockLedgerEntry` has no model-level immutable save/delete guard.
- Inventory document model saves can allow direct status changes without ledger posting; service functions are essential.
- Staff submitted documents do not enforce full model-level immutability.
- Direct `QuerySet.update()`, admin edits, migrations, and low-level ledger calls can bypass workflow guards.
- `Order.delete()` can be blocked by protected audit rows even when the order is an otherwise deletable draft.

## Incomplete or Divergent Features

- Printing is a success-only stub; production unit printer settings are not used.
- Return creation exists, but no return settlement or refund path exists.
- There is no customer master or customer search/create workflow.
- No separate reports app or department revenue posting exists.
- POS variant selection is modeled but not implemented.
- Discounts, partial payment, write-offs, taxes, and configurable rounding are not implemented; current rounding is always whole-unit half-up.
- Celery is configured but has no project tasks and an empty `SCHEDULED_TASKS` setting.

## Concurrency Risks

- Some service methods assume a caller acquired a lock, especially metadata update and closing draft creation.
- Shift cancellation methods check related state without explicit row locks.
- KOT cancellation relies on the order lock rather than independent KOT locks.
- First-time order sequence creation is less explicit under concurrency than later sequence increments.

## Access-Control Risks

- Most backoffice views rely on middleware, while only sensitive operations repeat role checks. Direct view invocation must not be assumed safe.
- `staff_assign_role()` removes current RestPOS groups before validating the requested role; an unknown role can strip a user's role.
- Historical detail accepts a primary key directly and can expose orders outside the caller's filtered history set.
- Historical receipt reprint is available to any authenticated user and does not update print metadata.

## Frontend/Backend Synchronization Risks

- HTMX target IDs and inline partial names are part of the contract; changing them breaks the POS silently.
- Alpine state is destroyed during fragment replacement. Persisted state must remain in session/database.
- Payment and closing totals shown while typing are client previews; only POST service calculations are authoritative.
- Catalog availability is annotated in memory and must be refreshed after cart reservation changes.

## Orphaned or Stale-Looking Code

- `web:pos_index` is shadowed by the earlier `/pos/` order include.
- `assets/javascript/floor-plan.js` references missing table layout endpoints/models.
- `app.js` and Chart.js are present/buildable but not used by the inspected active templates/source.
- `docs/archive/PLAN-history.md` mentions removed Branch, POSProfile, taxes, customers, price lists, and related architecture. Use current models/views/services as the behavioral authority.
- Some legacy templates use inline SVG/style conventions that differ from newer Hugeicons/Tailwind guidance.

## Refactoring Starting Points

If refactoring is later approved, begin with characterization tests around `orders.services.settle_order`, reservation conversion, ticket cancellation, and shift close. Then separate read-context construction from mutation orchestration. Do not begin by moving model guards without mapping the private transition flags and direct fixture updates used by tests.

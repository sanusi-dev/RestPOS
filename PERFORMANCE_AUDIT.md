# RestPOS Performance Audit

Date: 2026-08-08
Branch: `fix/performance-audit`

## Scope Inspected

The audit covered the application code, not the read-only `references/` tree or generated/vendor
directories.

- Django models, model methods, managers, constraints, and lifecycle workflows in all apps.
- Views, POS views, view helpers, URL configurations, and template context construction.
- ORM filters, joins, annotations, aggregates, prefetches, pagination, transactions, and locks.
- Django templates, HTMX endpoints, partials, OOB swaps, and template-side relation evaluation.
- Forms, inline formsets, dynamic formset row helpers, and choice querysets.
- Services, printing interface, management commands, signals, middleware, and context processors.
- Celery configuration and task discovery. No application Celery tasks or scheduled tasks are currently defined.
- Database, cache, static-file, Vite, and frontend bundle configuration.
- Existing tests and query-performance coverage.

## Baseline

The baseline was taken before the optimization changes.

| Check | Result |
|---|---:|
| Django tests | 611 passed in 817.134s |
| Ruff check | Passed |
| Mypy (`apps restpos`) | Passed |
| TypeScript check | Passed |
| Migration check | Passed |
| Orders | 68 |
| Order items | 247 |
| KOTs | 75 |
| Inventory items | 71 |
| Bins | 74 |
| Stock ledger entries | 198 |

Representative request measurements on the development database:

| Endpoint | Queries | Response bytes |
|---|---:|---:|
| `/pos/` | 13 | 21,368 |
| `/pos/history/` | 12 | 24,253 |
| `/backoffice/dashboard/` | 5 | 36,193 |
| `/backoffice/inventory/stock-ledger/` | 8 | 174,134 |

The cart-specific capture found four `orders_orderitem` queries during a cart render: one item
load followed by repeated template-side relation checks. Shift-close preview used four queries
for the current shift, including per-mode payment work.

## Findings

### Measured Bottlenecks

1. POS cart rendering queried order items repeatedly. Mutation views did not prefetch items, while
   cart templates called `order.items.exists` several times and iterated the relation again.
2. `Restaurant.load()` prefetched the full active-menu graph for POS home, history, payment, model,
   and form paths that did not render catalog data. The order context then issued another catalog
   query with different prefetches.
3. Cart responses always included the full catalog grid as an HTMX OOB fragment, including
   customer-card activation, metadata changes, and ticket retry actions that do not change catalog
   state.
4. Payment GET built the complete order context even though the payment fragment only needs the
   order totals and enabled payment modes.
5. POS history prefetched all items and payments only to display an item count.
6. The global `inventory_navigation` context processor counted item groups for public and POS
   responses. The inventory dashboard also calculated the same count independently.
7. Backoffice middleware reloaded the authenticated user row before prefetching groups, adding a
   duplicate user query to every POS and backoffice request.
8. Shift close calculated payment totals once per payment mode, then iterated submitted orders
   again for cash change. Closing totals were also calculated with three independent aggregates.
9. Opening-entry draft detail evaluated its opening-payment relation twice.

### Strongly Justified Risks Not Changed

1. Inventory registers and staff history lists are unbounded. The stock ledger is the clearest
   growth risk because it is immutable and grows for every stock movement.
2. Inventory posting performs per-line bin creation/locking and a latest-SLE lookup for each FIFO
   ledger entry. Reducing this further requires preserving lock order and valuation semantics.
3. Purchase receipt cancellation performs one prior-rate lookup per receipt line. A grouped query
   is possible, but duplicate item lines and historical ordering need dedicated coverage.
4. Return creation validates and saves each copied order line independently. A bulk path would need
   to preserve per-line return validation and historical snapshots.
5. Draft drink reservation changes recompute the whole order drink basket for each line mutation.
   This is correctness-sensitive because reservations are concurrency-protected.
6. Ticket dispatch currently holds a KOT transaction while calling the printer interface. The
   current printer implementation is simulated; the planned print-agent integration makes this
   external I/O and should use an outbox or post-commit job design.
7. The stock-ledger report filters by `posting_datetime__date`, which prevents a normal timestamp
   index from being used for the date predicate. A timezone-aware range filter should be benchmarked
   before changing this behavior.
8. Several inventory and staff lists are unpaginated. Pagination changes visible workflow behavior,
   so it is deferred until the desired page size and navigation contract are confirmed.

### Potential Frontend Optimizations

1. The site-wide bundle loads HTMX, Alpine, SweetAlert, Tom Select, the drawer module, and related
   CSS on public, POS, and backoffice pages. The measured generated assets total roughly 440 KB
   uncompressed before page-specific assets.
2. Font Awesome CSS and font files are included globally, but the inspected templates use inline
   SVGs and Hugeicons. Removal should follow a complete class-usage check.
3. Tom Select is initialized for every select after HTMX swaps. An opt-in selector for long choice
   lists could reduce DOM work, but short-select behavior should be explicitly approved first.
4. Several backoffice delete actions redirect to a full page and let HTMX select the target after
   the redirect. Returning a purpose-built fragment would reduce rendering and transfer work.

## Optimizations Implemented

1. `Restaurant.load()` now loads only direct singleton relations. Catalog callers still query the
   active menu explicitly, while unrelated requests no longer materialize menu items, item groups,
   or add-on graphs.
2. Cart context exposes the already loaded `order_items` and `has_items` values. Cart templates use
   those values instead of repeatedly evaluating the reverse manager.
3. Catalog OOB markup is now opt-in. It remains enabled for add, quantity, clear, send, and first
   receipt-print actions where catalog-visible state changes. It is omitted for metadata changes,
   customer-card activation, and ticket retry/reprint.
4. Payment GET now renders a minimal context containing the order and settleable payment modes.
   The full catalog, stock availability, ticket state, and cart grouping are not built for that
   fragment.
5. POS history rows use `Count("items", distinct=True)` and no longer prefetch unused item and
   payment objects.
6. Middleware uses `prefetch_related_objects` on the authenticated user instance instead of
   reloading the same user row.
7. The inventory-navigation count is limited to backoffice renders, and the inventory dashboard
   relies on that shared value instead of issuing a duplicate count.
8. Shift-close payment collection groups `OrderPayment` totals by mode and performs one distinct
   cash-change lookup. Closing totals are combined into one aggregate, closing-payment rows are
   reused, and opening-entry detail reuses its loaded payment rows.
9. Added three regression tests in `apps/orders/tests/test_performance.py` covering cart item-query
   bounds, payment-context query isolation, and history item-count annotation.

## After Measurements

The same development database and endpoint capture were used after the changes.

| Endpoint | Before queries | After queries | Response bytes after |
|---|---:|---:|---:|
| `/pos/` | 13 | 8 | 21,368 |
| `/pos/history/` | 12 | 7 | 24,253 |
| `/backoffice/dashboard/` | 5 | 4 | 36,193 |
| `/backoffice/inventory/stock-ledger/` | 8 | 7 | 174,134 |

The rolled-back draft-order capture measured these fragment paths after the change:

| Fragment/action | Queries | Order-item queries | Menu-item queries | Response bytes |
|---|---:|---:|---:|---:|
| Full order screen | 21 | 1 | 2 | 145,715 |
| Customer-card cart response | 19 | 1 | 2 | 30,871 |
| Payment dialog | 6 | 0 | 0 | 11,389 |

The customer-card response no longer includes the catalog OOB grid. Its smaller payload is a
technical consequence of returning only the changed cart. The previous cart capture issued four
order-item queries; the post-change regression path is bounded at one. Shift-close preview now
uses three queries for the same current-shift setup instead of four.

The post-change sequential suite passed `614` tests in `687.878s`. This is not treated as a
controlled application runtime benchmark because the run includes three new tests and uses the
preserved test database; the timing is recorded for operational context only.

## Indexes And Caching

No database indexes were added. Current `EXPLAIN` output on the development-sized database used
sequential scans for order/history and ledger reports, so adding write-costly indexes without a
production-sized dataset would be speculative. Candidate composite indexes should be revisited
with representative growth data, especially for shift/order status and stock-ledger date access.

No new cache was introduced. The cache configuration already uses a dummy backend in development
and Redis in production; the optimized paths remove unnecessary work without introducing cache
invalidation or stale configuration risks.

## Verification

- `uv run manage.py test --keepdb --verbosity 1`: passed, 614 tests.
- `uv run manage.py test apps.orders.tests`: passed, 207 tests.
- `uv run manage.py test apps.staff.tests`: passed, 63 tests.
- `uv run manage.py test apps.orders.tests.test_performance`: passed, 3 tests.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed.
- `uv run mypy apps restpos`: passed.
- `npm run type-check`: passed.
- `uv run manage.py makemigrations --check --dry-run`: passed.
- `git diff --check`: passed.

The first parallel targeted test attempt produced a PostgreSQL deadlock while separate test
processes inserted the same unique seed value into the preserved test database. The subsequent
sequential focused and full runs passed; no application failure was reproduced.

## Future Monitoring

- Track p95 query count and response size for POS cart mutations as the active menu and add-on
  catalog grows.
- Track shift-close query count and transaction duration with several payment modes and a full
  service-day order volume.
- Track stock-ledger report response size and database execution plans as ledger rows grow.
- Add a production-sized query-plan fixture before introducing composite indexes.
- Revisit asset splitting and static payload delivery separately from backend workflow changes.

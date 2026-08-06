# RestPOS Review

## Scope

This review covers the consolidated `feat/pos-shell-navigation` branch against
`origin/main`. The branch contains the history of the earlier inventory,
POS-redesign, settings, and order branches. Do not merge those older branches
separately.

All listed issues must be resolved before opening the PR. Fix P1 issues first
because they can corrupt data, money, or core workflows. P2 and P3 issues are
still required work; they are ordered later by urgency. Do not open the PR until
the complete list has been addressed and verified.

## P1 Blockers

### 1. POS crashes when no active menu exists

- **Location:** `apps/orders/views_pos.py`, `_build_order_context`
- **Problem:** The code accesses `settings.active_menu.enabled` when
  `active_menu` is `None`. Starting an order, adding an item, or updating order
  metadata can return HTTP 500.
- **Why it matters:** A valid restaurant configuration without an active menu
  makes the whole POS unusable.
- **Possible fix:** Guard both the settings object and the active menu before
  reading `.enabled`, matching the guard in the add-on dialog. Render a clear
  setup error when no active menu is configured.
- **Test:** Add a view test for an open shift with no active menu.

### 2. Disabled items can still be changed and settled

- **Location:** `apps/orders/models.py`, `Order.update_item_quantity`,
  `Order.settle`, and `_validate_pos_item`
- **Problem:** Availability is checked when a new line is added, but existing
  lines are not revalidated when their quantity is changed or the order is
  settled. An item or menu item disabled after it was added can still be sold.
- **Why it matters:** Backoffice disablement is not authoritative and a
  cashier can sell an item that should no longer be available.
- **Possible fix:** Add a central current-line validation method that checks
  the Item and active MenuItem state. Call it before quantity changes and before
  settlement.
- **Test:** Add an item, disable the item or menu item, then assert quantity
  update and settlement both fail without changing the order.

### 3. Duplicate electronic payment references can produce HTTP 500

- **Location:** `apps/orders/models.py`, `Order.settle` and `OrderPayment.save`
- **Problem:** The duplicate reference pre-check and the unique database
  constraint are a time-of-check/time-of-use pair. Concurrent settlements can
  raise `IntegrityError`, while the view catches only `ValidationError`.
- **Why it matters:** Cashiers see a server error instead of a recoverable
  duplicate-reference message, and the transaction behavior is unclear.
- **Possible fix:** Wrap payment-row creation in a nested atomic block, catch
  `IntegrityError`, and raise a user-facing `ValidationError`.
- **Test:** Simulate a duplicate reference at the constraint boundary and
  assert the order remains draft with a validation error.

### 4. GET close-shift requests create database records

- **Location:** `apps/orders/views_pos.py`, `pos_close_shift`
- **Problem:** A GET request can create a draft `POSClosingEntry` and child
  `ClosingPayment` rows.
- **Why it matters:** Refreshing or prefetching a page has a database side
  effect and creates reconciliation documents without an explicit action.
- **Possible fix:** Make GET render the close form or existing draft only. Move
  creation of the closing entry and payment rows into POST.
- **Test:** Assert a GET does not increase closing-entry or closing-payment
  counts.

### 5. Receipt printing occurs inside the database transaction

- **Location:** `apps/orders/views_pos.py`, `pos_order_print`
- **Problem:** The print agent is called inside the transaction before the
  invoice-printed state is saved.
- **Why it matters:** If printing succeeds and the later save fails, the
  receipt is physically printed but the database says it was not printed.
  Retrying can produce duplicates.
- **Possible fix:** Use a durable print-job/outbox record and process it after
  commit, or create an idempotent print-state workflow that can reconcile a
  successful print with a failed database update.
- **Test:** Simulate a save failure after a successful print and verify the
  retry path cannot silently duplicate the receipt.

### 6. Shift closing can use a stale period end

- **Location:** `apps/staff/models.py`, `POSClosingEntry.period_end_date` and
  `POSClosingEntry.submit`
- **Problem:** The closing cutoff is set when the draft closing entry is
  created. Orders settled after that point but before final submission can be
  excluded from reconciliation.
- **Why it matters:** Shift totals, payment totals, and audit records can be
  wrong.
- **Possible fix:** Under the opening-entry lock, set `period_end_date` to the
  current time immediately before calculating totals and submitting.
- **Test:** Create a closing draft, settle an order, submit the close, and
  assert the new order is included.

### 7. Cancelling an open shift can orphan orders and reservations

- **Location:** `apps/staff/models.py`, `POSOpeningEntry.cancel`, and
  `apps/staff/views.py`, `opening_entry_cancel`
- **Problem:** A shift can be cancelled without checking associated draft or
  submitted orders. Draft drink reservations can remain locked and submitted
  sales can become unreconciled.
- **Why it matters:** Stock availability and financial reconciliation can be
  permanently corrupted.
- **Possible fix:** Block cancellation when any order exists, or define and
  atomically execute a resolution flow that releases reservations and handles
  submitted orders.
- **Test:** Cover cancellation with draft reservations and with submitted
  sales.

### 8. Failed cancellation-ticket printing has no recovery path

- **Location:** `apps/orders/views_pos.py`, `pos_order_cancel` and
  `pos_order_ticket_print`
- **Problem:** A cancellation KOT can remain pending after a print failure, but
  the retry endpoint only accepts draft orders. The cancellation response can
  still report success.
- **Why it matters:** The kitchen or bar may continue preparing a cancelled
  order and the cashier has no way to resend the cancellation ticket.
- **Possible fix:** Surface print failure, keep the ticket pending, and allow a
  retry action for pending cancellation tickets on cancelled orders.
- **Test:** Simulate a failed cancellation print, then retry it successfully.

### 9. POS seed command leaves Central Store unconfigured

- **Location:** `apps/orders/management/commands/seed_pos_setup.py`
- **Problem:** The command creates a Store warehouse but assigns only the Bar
  warehouse to `Restaurant.default_warehouse`.
- **Why it matters:** Stock receipts and material transfers that require
  `Restaurant.store_warehouse` fail after running the setup command.
- **Possible fix:** Assign `restaurant.store_warehouse` to the created Store
  warehouse and save both warehouse references.
- **Test:** Run the command and assert both warehouse fields are configured.

### 10. Submitted inventory documents can be edited and reposted

- **Location:** `apps/inventory/admin.py` and `apps/inventory/models.py`
- **Problem:** Django admin permits editing submitted stock entries and
  reconciliations. Re-submitting changed lines can duplicate stock ledger
  movements.
- **Why it matters:** Inventory balances and the audit trail become incorrect.
- **Possible fix:** Make submitted fields read-only, block changes and deletes,
  and require explicit cancellation/reversal documents.
- **Test:** Attempt admin/model mutation of submitted documents and assert it is
  rejected.

### 11. Singleton migration can fail with duplicate legacy Restaurants

- **Location:** `apps/settings/migrations/0017_single_location_data.py` and
  `0023_restaurant_singleton_key_and_more.py`
- **Problem:** The migration adds a unique singleton key without handling more
  than one existing Restaurant row.
- **Why it matters:** A valid legacy database can fail deployment during
  migration.
- **Possible fix:** Validate row count before adding the constraint and either
  stop with an actionable error or deterministically consolidate the rows.
- **Test:** Run the migration with multiple legacy Restaurant rows.

## P2 and P3 Issues

### 12. Shift submit/cancel confirmations do not work consistently

- **Location:** `assets/javascript/confirm.js` and staff opening/closing
  templates
- **Problem:** Confirmation JavaScript expects one set of data attributes while
  normal staff forms use another set. Irreversible actions can submit without
  confirmation.
- **Possible fix:** Standardize all confirmation attributes and use the same
  SweetAlert/confirmation handler for HTMX and normal forms.

### 13. Payment configuration permits zero defaults

- **Location:** `apps/payments/models.py` and payment seed migration
- **Problem:** The database enforces at most one default payment mode, not at
  least one. A fresh setup can have no default.
- **Possible fix:** Seed exactly one default, prevent unsetting the only
  default without replacement, and add a configuration validation test.

### 14. Cashiers can access manager-only history statuses

- **Location:** `apps/orders/views_pos.py`, `templates/pos/order_history.html`
- **Problem:** All, Returns, Cancelled, and Discarded filters are exposed to
  every POS user, while the feature specification describes full history as a
  manager-controlled capability.
- **Possible fix:** Gate non-sales filters behind the manager permission or a
  restaurant setting.

### 15. History and register results are silently capped at 50

- **Location:** `apps/orders/views_pos.py` and backoffice order views
- **Problem:** Results are sliced to 50 without pagination controls.
- **Possible fix:** Use Django `Paginator`, preserve active filters in page URLs,
  and add previous/next/page controls.

### 16. Close-shift navigation disappears on history

- **Location:** `templates/pos/base.html` and `pos_order_history`
- **Problem:** The base template checks for a `shift` context variable, but the
  history view only stores the active shift locally as `open_shift`.
- **Possible fix:** Pass `shift=open_shift` into the history context or expose
  the active shift through a shared POS context processor.

### 17. POS layout clips on narrow screens

- **Location:** POS cart and catalog sidebar templates
- **Problem:** The cart requires a wide minimum width and the sidebar is fixed
  width. Narrow screens lose catalog or cart content.
- **Possible fix:** Collapse the sidebar and cart into responsive slide-over
  panels or remove hard minimum widths below tablet breakpoints.

### 18. Payment and add-on dialogs do not trap focus

- **Location:** `templates/pos/partials/payment/dialog.html` and
  `templates/pos/partials/catalog/add_on_dialog.html`
- **Problem:** Focus can move behind an `aria-modal` dialog, and focus is not
  reliably restored when the dialog closes.
- **Possible fix:** Reuse the order-details focus controller or create a shared
  Alpine dialog component with Tab trapping, Escape close, and focus restore.

### 19. Customer-card activation does not refresh catalog OOB

- **Location:** `apps/orders/views_pos.py`, `pos_customer_card_activate`
- **Problem:** The response returns only the cart partial while other cart
  actions return the catalog availability OOB refresh.
- **Possible fix:** Use the shared cart renderer consistently, or explicitly
  document and test why this action does not need a catalog refresh.

### 20. Order-type controls remain enabled after receipt printing

- **Location:** `templates/pos/partials/cart/guests.html`
- **Problem:** Guest controls check `invoice_printed`, but order-type controls
  check only whether the order was sent. The UI permits an action the server
  rejects.
- **Possible fix:** Include `order.invoice_printed` in the disabled and locked
  conditions.

### 21. Order saves perform redundant queries

- **Location:** `apps/orders/models.py`, `Order.save` and `OrderItem.save`
- **Problem:** Each save reloads the order and repeats editability/KOT checks.
  Cart operations can produce several unnecessary queries per line.
- **Possible fix:** Use narrowly selected state queries, cache the persisted
  order state during one operation, and avoid duplicate editability lookups.

### 22. `_get_pos_order` is dead code

- **Location:** `apps/orders/views_pos.py`
- **Problem:** The helper is defined but has no callers, leaving two competing
  patterns for retrieving POS orders.
- **Possible fix:** Remove it or use it consistently in all POS order views.

### 23. Cash change can be attributed multiple times

- **Location:** `apps/staff/models.py`, closing reconciliation
- **Problem:** `Order.change_amount` is order-level but is subtracted from every
  cash payment mode. Multiple cash modes can double-count change.
- **Possible fix:** Enforce one cash mode or allocate change to a specific
  payment row.

### 24. Legacy reconciliation reasons are guessed

- **Location:** `apps/inventory/migrations/0023_backfill_stock_reconciliation_reason.py`
- **Problem:** Missing historical reasons are classified as
  `PHYSICAL_COUNT`, which may be false.
- **Possible fix:** Add a `LEGACY_UNSPECIFIED` reason or preserve the missing
  value and require manual review.

## Resolved Finding

### 25. History default filter included drafts and cancelled orders

This finding is resolved. The current default history query filters to submitted,
paid, non-return orders. Keep the regression test in place.

## Tooling and Test Gaps

### 26. Full test suite is not clean

The last review observed 2 failures and 1 error in payment seed tests. Reproduce
with a fresh test database to distinguish a migration problem from stale
`--keepdb` state, then fix the underlying setup or tests.

### 27. Type checking includes read-only reference JavaScript

`npm run type-check` reaches JavaScript under `references/erpnext-develop/` and
fails there. Exclude `references/` from the project TypeScript configuration or
use a project-only tsconfig.

### 28. No browser-level POS coverage

The drawer animation, focus trap, responsive layout, keyboard behavior, and OOB
swaps are not covered by browser tests. Add a small Playwright smoke suite when
browser testing is approved.

## Recommended Agent Order

1. Fix P1 issues 1-11 and add regression tests.
2. Fix the full-suite payment test/migration problem.
3. Fix P2 issues that affect financial integrity, permissions, and history
   access: 12-16 and 23-24.
4. Fix responsive and accessibility issues: 17-20 and 28.
5. Clean up performance/dead-code issues: 21-22.
6. Exclude reference code from type checking.
7. Run Django checks, migrations check, full tests, Ruff, and project-only type
   checks.
8. Run a fresh review of `feat/pos-shell-navigation` against `origin/main`.

## Verification Commands

```text
make test ARGS='--keepdb'
make ruff
make manage ARGS='makemigrations --check'
make npm-type-check
```

Do not modify anything under `references/`. Do not merge older branches into the
shell branch; their commits are already contained in it.

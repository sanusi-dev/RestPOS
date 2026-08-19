# Shift Workflow

## Domain Objects

`POSOpeningEntry` is the global shift parent. `OpeningPayment` stores one opening balance per enabled payment mode. `POSClosingEntry` is a one-to-one close document and `ClosingPayment` stores counted, expected, and difference values. The opening remains `SUBMITTED` after close; `closing_entry_id` determines whether it is open or closed.

## Opening

### POS path

`templates/pos/partials/gates/no_shift.html` renders one amount input per enabled `ModeOfPayment`. `pos_open_shift()` binds `OpeningFloatForm`, requires at least one enabled mode, and calls `staff.services.open_shift()`.

`open_shift()` (`apps/staff/services.py:99-124`) runs atomically, locks `Restaurant`, checks for an existing open shift, creates the opening and child rows, validates the entry, and calls `POSOpeningEntry.submit()`. The model method repeats the one-open-shift check while holding the Restaurant and open-shift locks.

### Backoffice path

`staff.views.opening_entry_create()` and `_save_opening_entry()` create a draft and bulk-create `OpeningPayment` rows. `opening_entry_detail()` lets a draft be edited by replacing its child rows. `opening_entry_submit()` calls `full_clean()` and then `entry.submit()`.

⚠️ Requires verification: the backoffice create path does not call `staff.services.open_shift()` and can therefore bypass that service's explicit "Restaurant settings exist" check. The model submit path still enforces the one-open-shift rule.

## Open Shift Rules

- Exactly one global open shift is intended, not one per cashier.
- Any staff-role user can use the active shift; there is no post-opening cashier ownership check.
- New orders, settlement, and close all validate `status=SUBMITTED` and `closing_entry IS NULL`.
- Opening cancellation is blocked once any order row exists, including cancelled or discarded rows.
- A closed opening cannot be cancelled; cancel the closing entry instead.

## Closing

POS GET `/pos/close-shift/` computes expected values without creating database rows. If open drafts exist, it renders a blocking page. POS POST locks the opening row, rechecks drafts, creates/reuses a closing draft, saves counted amounts, updates period end, and calls `submit_closing_entry()`.

Backoffice `closing_entry_create()` locks the open shift to prevent duplicate closing drafts. The detail page edits draft counted amounts. Both POS and backoffice ultimately call the same closing service.

`submit_closing_entry()`:

1. Locks the closing and opening rows.
2. Sets the authoritative period end to submit time.
3. Blocks any open draft orders.
4. Aggregates submitted non-return orders in the period.
5. Computes expected per-mode amounts as opening float plus order payments, less cash change.
6. Stores closing differences as `closing_amount - expected_amount`.
7. Applies the variance approval gate: when the absolute `total_short_excess` exceeds `Restaurant.variance_approval_threshold`, a non-empty `variance_note` and a Manager/Admin actor are required.
8. Submits the closing and links it to the opening.
9. Posts the cash variance: when `total_short_excess != 0` and the account matching the variance sign (`cash_shortage_account` or `cash_over_short_account`) is configured, `accounting.services.post_cash_variance_gl` creates and submits a balanced JournalEntry (shortage → Dr shortage / Cr cash; excess → Dr cash / Cr over-short) linked via `POSClosingEntry.variance_journal_entry`. Unconfigured accounts skip posting but the variance stays visible.

Returns are excluded from drawer totals. Cancelled orders are excluded through `submitted_in_shift()`.

## Closing Cancellation

`POSClosingEntry.cancel()` marks only the closing row cancelled. It does not reopen the opening. It is blocked if a newer open shift exists, because reopening an older period would overlap the live shift. When the close posted a variance JournalEntry, cancelling first reverses that journal (mirrored negated GL rows).

## Failure Cases and Risks

- POST close can create and commit a draft closing entry before invalid form data is rendered.
- `ClosingPaymentForm` has client-side `min=0`, but no server-side non-negative validator; negative counted amounts are not rejected by the model.
- The service validates that closing modes were declared at opening but does not require exactly one closing row for every opening row.
- Closing is serialized by opening/closing row locks, but model-level cancel methods do not explicitly lock before their checks.

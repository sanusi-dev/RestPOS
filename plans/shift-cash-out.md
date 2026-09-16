# Shift Cash-Out Voucher — Implementation Plan

**Status:** proposed (awaiting developer review; not yet in `PLAN.md` / `FEATURES.md`).
**Scope:** one lightweight voucher in `apps/staff` plus GL legs and POS dialog.
No change to refunds, market receipts, Daily P&L memos, or variance posting.

## 1. Objective

Record cash leaving the drawer mid-shift for non-stock reasons (transport, ice, petty
repairs) so the drawer balances truthfully at close and the books carry the expense.
Single-step record with manager-only cancel while the shift is open — deliberately not
Draft/Submit, because the shift close itself is the review point and speed at the
till matters.

## 2. Models (`apps/staff`)

**ShiftCashOut**

| Field | Type | Notes |
|---|---|---|
| `opening_entry` | FK POSOpeningEntry, CASCADE, `related_name="cash_outs"` | the shift it belongs to |
| `mode_of_payment` | FK ModeOfPayment, PROTECT | cash modes only (see rules) |
| `amount` | Decimal(12,2) | `> 0` |
| `reason` | choices TRANSPORT / ICE / PETTY_REPAIRS / OTHER, default OTHER | |
| `note` | CharField(200) blank | required when reason is OTHER |
| `status` | SUBMITTED / CANCELLED | created SUBMITTED, never DRAFT |
| `recorded_by` | FK CustomUser, PROTECT | cashier who recorded it |
| `cancelled_by` / `cancelled_at` | FK nullable / DateTime nullable | set on cancel |

`clean()`: mode must be enabled, `type == CASH`, and declared in the shift's
`opening_payments` (same membership rule as `ClosingPayment.clean`,
`models.py:281-288`); amount `> 0`; OTHER requires non-blank note; shift must still be
open (`opening_entry.is_open`) for both record and cancel.

**Settings:** `Restaurant.petty_cash_expense_account` (FK LedgerAccount, PROTECT,
nullable). Record resolves it, falling back to `Restaurant.default_expense_account`;
fails closed when neither is set. `seed_chart_of_accounts` creates "Petty Cash Expenses"
under Expenses and wires the FK only when null (same idempotent pattern as §4.2 seeds).

## 3. Business rules

- `record_cash_out(opening, *, mode, amount, reason, note, actor)` (`staff/services.py`,
  atomic): validates via `full_clean()`, creates the SUBMITTED row, then posts GL —
  `voucher_type="Shift Cash-Out"`, `voucher_no=<record number>`: Dr petty-cash/default
  expense / Cr the cash mode's GL mapping, `against` mirrored. Idempotent per row
  (GL keyed to the row pk; second call returns without re-posting).
- `cancel_cash_out(row, *, actor)`: manager/admin only; refused when the shift is closed
  or the row is already CANCELLED. Posts mirrored negated legs, originals
  `is_cancelled=True`, row flips CANCELLED with by/at stamps.
- Expected drawer (`expected_closing_amounts`, `services.py:53-81`): subtracts submitted
  cash-outs per mode alongside the existing collected-minus-refunded maths. No stored
  field changes on the close — `submit_closing_entry` recomputes `ClosingPayment`
  rows from the same function, so cash-outs flow in automatically. Cancelling the close
  leaves vouchers intact (they belong to the still-open shift); re-submit recomputes.
- Daily P&L: untouched. Cash-outs are GL + drawer truth, not P&L memos; the Daily P&L
  indirects section may read them in a later pass (explicitly out of scope).

## 4. Frontend

- POS (`apps/orders/views_pos.py`, `@staff_required`; cancel keeps an in-view
  manager-only check like ticket reprint): `pos_cash_out_dialog` (GET dialog fragment),
  `pos_cash_out_record` (POST, returns shift fragment + `HX-Trigger: close-cash-out`),
  `pos_cash_out_cancel` (POST, manager only). Routes live beside
  `pos_open_shift`/`pos_close_shift` in `pos_urls.py` (shift-level, not order-level).
- `variant_dialog`-style modal (`add_on_dialog.html:1-53` pattern, Alpine
  `posModalDialog`): amount input, cash-mode select (cash modes of this shift only),
  reason radio/dropdown, note field, live "Expected cash after this: ₦X" preview
  computed from current expected minus amount, SweetAlert confirm on submit.
- Visibility: "Shift cash-outs" section on the POS shift screen and read-only on the
  closing-draft/submitted detail above the reconciliation table (time, recorder, reason,
  amount, status; Cancel button per row while open). Close Details formula text from
  the Z-report plan gains "− cash-outs".

## 5. Tests

`apps/staff/tests/test_shift_cash_out.py` (new):

- Record reduces that mode's expected by amount; other modes untouched; submit stores
  the reduced expected on `ClosingPayment`.
- GL legs Dr expense / Cr cash-mode account with voucher link; missing expense chain
  fails closed; cancel posts reversal and restores expected.
- Non-cash mode, mode outside opening set, zero/negative amount, OTHER-without-note
  all rejected; record/cancel on a closed shift refused; cancel by cashier refused.
- Cashier can record; cashier cannot cancel; manager can do both.

## 6. Docs (same task)

- `docs/workflows/shifts.md` + `docs/execution-flows/close-shift.md`: voucher lifecycle,
  expected formula with cash-outs, GL map.
- `FEATURES.md` A5: one row for the voucher; #26 refund-netting line extended with
  "and cash-outs".

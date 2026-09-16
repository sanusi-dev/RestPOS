# Shift Close Z-Report — Implementation and Fix Plan

**Status:** proposed (awaiting developer review; not yet in `PLAN.md` / `FEATURES.md`).
**Scope:** display-only fix plus two stored fields. No change to closing maths, guards,
variance posting, or cancel rules.

## 1. Problem

The close computes shift sales at submit but never shows them. The help text describes a
pre-sales system that no longer exists.

- `submit_closing_entry` (`apps/staff/services.py:162-174`) aggregates
  `total_quantity / net_total / grand_total` over `submitted_in_shift` and stores them on
  `POSClosingEntry` (`models.py:178-180`). Bill count and refunded total are not stored.
- `closing_entry_detail.html:29-72` renders cashier/opening/status/short-excess/variance
  only; `:73-157` renders the per-mode drawer table only. No bills, qty, net, grand,
  or refunded figure appears anywhere. `closing_entry_list.html` shows short/excess only.
- The yellow box (`closing_entry_detail.html:80-86`) says "there is no order tracking
  yet, so expected equals opening" and "in Phase 7, once sales are tracked…". Both
  clauses are stale: order tracking landed in Phase 5 and Expected already equals
  opening + collected − refunds, net of cash change (`services.py:53-81`).

## 2. Decisions

- Add two stored fields to `POSClosingEntry` (both `editable=False`, set once at submit,
  never edited after — same immutability as the existing three totals):
  - `bill_count` (PositiveInteger, default 0): count of `submitted_in_shift` orders.
  - `refunded_total` (Decimal(14,2), default 0): sum of submitted return `grand_total`
    abs values in the same period (same return queryset as `expected_closing_amounts:58-64`).
- `submit_closing_entry` sets all five (`bill_count`, `total_quantity`, `net_total`,
  `grand_total`, `refunded_total`) inside the existing atomic block before flipping
  SUBMITTED. Computation reuses the exact querysets already there; no new maths.
- Data migration backfills the two fields for existing SUBMITTED closings using the same
  querysets. Draft closings recompute naturally on their next submit.
- Detail page gains a "Shift sales" block inside Close Details (above Total Short/Excess):
  Bills, Item qty, Net total, Grand total, Refunded total. All read from stored fields —
  never recomputed live — so the slip is frozen like the rest of the close.
- List page gains a Net sales column (`grand_total`) for scanning across shifts.
- Yellow box rewritten to the true formula: "Opening = float at shift start. Expected =
  opening + collected sales − refunds, net of cash change given. Closing = counted.
  Difference = closing − expected." The Phase-7 sentence is deleted.
- Cancel path unchanged (`models.py:228-253`): cancelling a close does not touch the
  stored sales fields; a re-submit recomputes them.

## 3. Frontend

- `closing_entry_detail.html`: sales `<div>` rows following the existing `dt/dd` pattern
  (`:33-50`); no new styling, no new components. Numbers use the same mono tabular style
  as `:54`.
- List template: one right-aligned Net column reusing the existing short/excess cell style.
- No HTMX, no Alpine, no new pages, no new URLs.

## 4. Tests

`apps/staff/tests/test_closing_z_report.py` (new):

- Submit stores bills/qty/net/grand/refunded matching a hand-built shift (2 paid orders +
  1 partial return: bills counts paid only, refunded nets the return's `grand_total`).
- Detail renders all five stored values; list shows net column.
- Draft submit with zero orders stores zeros and still closes (existing guard is open
  drafts, not zero sales).
- Backfill migration: pre-migration SUBMITTED close gains correct bill_count/refunded.
- Variance threshold, variance JE linkage, and cancel-blocked-by-newer-shift unchanged.

## 5. Docs (same task)

- `docs/workflows/shifts.md`: sales block documented as stored-at-submit; formula corrected.
- `docs/execution-flows/close-shift.md`: trigger→view→service→stored-fields→fragments updated.
- `FEATURES.md` A5 #24: one clause added ("closing detail shows shift sales totals").

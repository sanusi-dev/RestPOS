# Register Exports (CSV) — Implementation Plan

**Status:** proposed (awaiting developer review; not yet in `PLAN.md` / `FEATURES.md`).
**Scope:** CSV download on four existing registers. No Excel/PDF engine, no new dependency.

## 1. Objective

Let the accountant work without a POS login: download exactly what the back-office list
currently shows, with the same filters applied. CSV opens directly in Excel, so no
`openpyxl`/`reportlab`/`weasyprint` dependency is added — stdlib `csv` only.

## 2. Decisions

- Four exports, each a `GET ?export=csv` variant of its list view (same URL, same
  permission gate, same filter params — no new permission surface):
  1. Orders register (`orders:order_list`; backoffice gate): search/status/order_type as today (`apps/orders/views.py:74-111`).
  2. GL entries (`accounting:gl_entry_list`; manager gate): existing fiscal/account/date filters.
  3. Stock ledger (`inventory:stock_ledger_list`; backoffice gate): existing item/warehouse/date filters.
  4. Daily P&L list (`reports:daily_pnl_list`; manager gate): existing status/from/to filters.
- Stock balance (`inventory:stock_balance_list`) is excluded v1 — it is a computed
  opening/received/issued/closing view, not a row table; revisit only on accountant request.
- CSV shape: UTF-8 with BOM (Excel-friendly), header row in plain English, one row per
  table row, same ordering as the page, totals row appended where the page shows one.
  Columns:
  - Orders: invoice, order no, date, time, cashier, type, customer, status, net, grand, paid, change.
  - GL: posting date, account, debit, credit, against, voucher type, voucher no, fiscal year, cancelled flag.
  - Stock ledger: posting date, item, warehouse, voucher type/no, qty, unit rate, value change, variance.
  - Daily P&L: business date, status, food sales, drinks sales, net sales, gross profit, net profit.
- Money formatting: raw two-decimal values (no `₦`, no thousands separators) so Excel sums work.
- Safety: `StreamingHttpResponse` with `Content-Disposition: attachment`; filename carries
  register + timestamp + active filters (e.g. `orders-2026-09-11-status-SUBMITTED.csv`).
  Row cap 50,000 with an HTTP 400 + message above it (prevents accidental full-history dumps
  locking the cashier desktop). No pagination params — export always means "all matching".
- Empty result exports headers only (still 200).

## 3. Frontend

- One "Download CSV" link per list page beside the existing filter form, preserving current
  querystring plus `export=csv`. No new pages, no new filters, no styling system change.
- No HTMX swap: plain link navigation returning the file.

## 4. Tests

`apps/<app>/tests/test_register_exports.py` (one per app, same file as list tests where present):

- Filter parity: export with `?status=…&from=…` returns exactly the filtered rows, same order.
- Header + BOM present; money cells parse as decimals in Python `csv` reader.
- Permission gates match the page (cashier/anonymous denied same as list view).
- Cap: queryset above cap returns 400 with message; at-cap exports fully.
- Empty filter set returns headers-only CSV, not an error.

## 5. Docs (same task)

- `docs/workflows/backoffice.md` reporting surfaces: one line per export (URL + filters + filename pattern).
- `FEATURES.md`: append "CSV export" to the four register rows (orders control room, GL entries, stock ledger, Daily P&L list). No new feature number.
- Deferred explicitly: `.xlsx` formatting, PDF statements, scheduled email exports.

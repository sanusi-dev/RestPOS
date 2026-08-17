# Order Workflow

## Order as the Operational Document

`Order` in `apps/orders/models.py` is the source of truth for order lines, payment rows, totals, lifecycle, shift ownership, receipt-printed state, stock warehouse snapshot, returns, and audit events. It is not an accounting invoice model and does not have a separate receipt or customer record.

## Creation and Editing

`create_draft_order()` checks Restaurant settings, locks the active shift, enforces `max_open_drafts`, creates a draft, assigns a human order number, and records `CREATED`. `Order.save()` assigns `arrived_time` and an invoice number such as `REST-42` on insert.

Line addition uses menu pricing and snapshots item data. Identical item/customer/comment lines merge. Add-ons become separate order lines. `recalculate_totals()` sums line amounts, sets net and grand totals, and calculates whole-unit half-up rounding.

Order edits are rejected when the order is submitted, cancelled, discarded, or has KOTs. A printed receipt is no longer a draft lock — only a kitchen/bar ticket (KOT) freezes draft edits. Guest count can rise to 50 but cannot drop below the highest customer index containing items.

## Customer Grouping

Grouping is presentation-only. `guest_count` lives on the order; `customer_index` lives on each line and is copied into KOT lines. The session's active card selects where the next line is added. No lines are silently re-tagged when guest count changes.

## KOT/BOT Snapshot

`create_tickets()` takes a single-send snapshot of current lines, routes FOOD and DRINKS to their configured production units, and creates KOT/BOT rows. A takeaway station can suppress its ticket with `block_takeaway_kot`. The order remains a draft after sending, but its lines become locked.

## Submission

`settle_order()` is the only normal path from draft to submitted. It locks the order and shift, revalidates current lines and stock, creates payment rows, applies rounded total/payment/change values, converts drink reservations into stock issues, marks the order paid/submitted, sets `invoice_printed`/`invoice_printed_at`/`invoice_printed_by` (settlement *is* the receipt event), and adds `SUBMITTED` audit data. The view calls `printing.print_receipt(order)` after settlement; a printer failure shows a warning but never rolls back the sale. Receipts are reprinted from order history (`pos_order_history_print`, submitted orders only).

## Stage Exits — Delete, Cancel, Return

Each order stage has exactly one exit (PLAN.md §6.24, deviation from ERPNext/URY):

1. **Draft, nothing sent** (no KOT) — **delete** freely. `Order.delete()` removes the draft, its item rows, and its audit events (the event rows are purged via the queryset because `OrderAuditEvent` refuses instance deletion), and releases drink reservations. The POS "Delete order" button posts to `pos_order_delete`; the backoffice "Delete draft" button posts to `order_delete` (manager-only). There is no cancellation path for unsent drafts — `cancel_order()` and `cancel_sent_order()` both reject them with "delete it instead".
2. **Sent to kitchen/bar** (KOT exists) — **cancel only**, never delete. `cancel_sent_order()` (POS) or `cancel_order()` (backoffice) requires a reason, creates cancellation KOTs for each station, releases drink reservations, lands on the per-cashier cancel report, and preserves items/payments for audit.
3. **Paid (submitted)** — **return only**, never cancel. `make_return()` creates a negative-item return draft linked to the source. `submit_return()` submits it: re-validates each return line, restores drink stock via positive SLEs (`voucher_type="POS Return"`), mirrors each source payment as a negative `OrderPayment` (`reference_no=""` so the payment-reference unique constraint cannot collide), sets `paid_amount` to the negative refund total (immutable `SUBMITTED` status, `is_paid` stays `False`), and appends `RETURN_SUBMITTED` audit data. The backoffice "Submit return" button is manager-only.

`discard_order()` still exists only for legacy seed data and marks an empty untouched draft as `DISCARDED`; the POS path was removed. `DISCARDED` stays in the status choices for historical rows.

## Audit Events

The service layer appends events such as `CREATED`, `ITEM_ADDED`, `ITEM_REMOVED`, `ITEM_QUANTITY_CHANGED`, `ITEMS_CLEARED`, `ORDER_TYPE_CHANGED`, `GUEST_COUNT_CHANGED`, `KOTS_CREATED`, `SUBMITTED`, `CANCELLED`, `DISCARDED`, `RETURN_CREATED`, and `RETURN_SUBMITTED`. `OrderAuditEvent` cannot be updated or deleted.

## Important Invariants

- Normal order line quantity is positive; return line quantity is negative and references an original line.
- Rates are non-negative Decimal values and amounts are quantized to two decimal places.
- Historical item name/department/stock flags are snapshots, so later Item changes do not rewrite old lines.
- Human order numbers are assigned through a locked `OrderSequence` counter.
- Direct `QuerySet.update()` can bypass `save()` guards; service and model paths are the intended behavior.

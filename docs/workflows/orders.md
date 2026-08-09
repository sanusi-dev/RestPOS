# Order Workflow

## Order as the Operational Document

`Order` in `apps/orders/models.py` is the source of truth for order lines, payment rows, totals, lifecycle, shift ownership, receipt claim, stock warehouse snapshot, returns, and audit events. It is not an accounting invoice model and does not have a separate receipt or customer record.

## Creation and Editing

`create_draft_order()` checks Restaurant settings, locks the active shift, enforces `max_open_drafts`, creates a draft, assigns a human order number, and records `CREATED`. `Order.save()` assigns `arrived_time` and an invoice number such as `REST-42` on insert.

Line addition uses menu pricing and snapshots item data. Identical item/customer/comment lines merge. Add-ons become separate order lines. `recalculate_totals()` sums line amounts, sets net and grand totals, and calculates whole-unit half-up rounding.

Order edits are rejected when the order is submitted, cancelled, discarded, receipt-printed, or has KOTs. Guest count can rise to 50 but cannot drop below the highest customer index containing items.

## Customer Grouping

Grouping is presentation-only. `guest_count` lives on the order; `customer_index` lives on each line and is copied into KOT lines. The session's active card selects where the next line is added. No lines are silently re-tagged when guest count changes.

## KOT/BOT Snapshot

`create_tickets()` takes a single-send snapshot of current lines, routes FOOD and DRINKS to their configured production units, and creates KOT/BOT rows. A takeaway station can suppress its ticket with `block_takeaway_kot`. The order remains a draft after sending, but its lines become locked.

## Submission

`settle_order()` is the only normal path from draft to submitted. It locks the order and shift, revalidates current lines and stock, creates payment rows, applies rounded total/payment/change values, converts drink reservations into stock issues, marks the order paid/submitted, and adds `SUBMITTED` audit data.

## Cancellation, Discard, and Return

- Sent/printed unpaid POS drafts use `cancel_sent_order()` and create cancellation KOTs.
- Backoffice `cancel_order()` can cancel drafts and submitted unpaid orders; it reverses submitted drink stock and preserves payments/items for audit.
- Paid submitted orders must use return flow, not cancellation.
- `discard_order()` marks an empty untouched draft as `DISCARDED`; it does not delete it.
- `make_return()` creates a negative draft linked to a submitted paid source. No service currently submits or refunds it.

## Audit Events

The service layer appends events such as `CREATED`, `ITEM_ADDED`, `ITEM_REMOVED`, `ITEM_QUANTITY_CHANGED`, `ITEMS_CLEARED`, `ORDER_TYPE_CHANGED`, `GUEST_COUNT_CHANGED`, `KOTS_CREATED`, `RECEIPT_PRINTED`, `SUBMITTED`, `CANCELLED`, `DISCARDED`, and `RETURN_CREATED`. `OrderAuditEvent` cannot be updated or deleted.

## Important Invariants

- Normal order line quantity is positive; return line quantity is negative and references an original line.
- Rates are non-negative Decimal values and amounts are quantized to two decimal places.
- Historical item name/department/stock flags are snapshots, so later Item changes do not rewrite old lines.
- Human order numbers are assigned through a locked `OrderSequence` counter.
- Direct `QuerySet.update()` can bypass `save()` guards; service and model paths are the intended behavior.

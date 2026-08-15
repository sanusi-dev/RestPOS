# Receipts and Printing

## Current Implementation

Printing is represented by a narrow interface in `apps/orders/printing.py`:

- `print_ticket(ticket) -> PrintResult`
- `print_receipt(order) -> PrintResult`

Both functions currently return `PrintResult(success=True, ...)` without formatting or communicating with a device. `ProductionUnit` stores `printer_ip`, paper width, and cut mode, but those values are not consumed by the current print functions.

## Receipt Claim

`pos_order_print()` calls `services.claim_receipt_print()` inside a transaction. The service locks the draft, requires at least one item, marks `invoice_printed`, stores time/user, and appends `RECEIPT_PRINTED`. The transaction commits before `printing.print_receipt(order)` runs.

This ordering means a failed physical print leaves the order marked printed and the next action is a reprint. It intentionally prioritizes preventing a successful print from being followed by an unprinted database state. Because the current stub always succeeds, real failure behavior is not exercised outside tests.

## Ticket Dispatch

`create_tickets()` creates KOT/BOT rows with `print_status=PENDING`. `dispatch_tickets()` processes each ticket in its own transaction, locking the row, calling `print_ticket()`, and changing status to `PRINTED` only on success. Failure leaves the ticket pending for retry.

Food routes to the FOOD ProductionUnit; drinks route to DRINKS. Cancellation creates a new cancellation ticket per station, while original tickets become cancelled. Cancellation-ticket printing can fail independently after order cancellation has committed.

`settle_order()` guarantees ticket records: when a settling order has no KOTs, it plans tickets with the same departmental routing (`_plan_tickets`) and builds NEW_ORDER snapshots (`_build_ticket_snapshots`), then dispatches them inside the settlement transaction. Print failure never blocks settlement — the ticket stays `PENDING` for retry.

## Retry and Reprint

`pos_order_ticket_print()` accepts `retry` for pending tickets and `reprint` for printed tickets, on draft, cancelled, and submitted orders. Reprint is manager/admin/superuser-only. The selected ticket is locked and selected in a transaction; the physical call occurs afterward. Historical receipt reprint accepts submitted orders and does not update `invoice_printed` metadata.

On a submitted order, the history detail screen shows a "Retry kitchen/bar ticket" action for each pending NEW_ORDER ticket.

## Templates

Receipt/ticket controls are in `templates/pos/partials/cart/totals.html` and `templates/pos/order_history_detail.html`. There is no receipt template, ESC/POS formatter, print agent, printer client, or print job table in the current code.

⚠️ Requires verification: the intended production printer topology in `AGENTS.md` and `FEATURES.md` is not implemented by the current runtime. Treat those files as design context, not an available integration.

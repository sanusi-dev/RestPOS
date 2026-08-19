# Execution Flow: Backoffice Order Operations

## Register and Detail

```text
Backoffice order navigation
  -> apps/orders/urls.py
  -> orders.views.order_list()
  -> search/filter Order queryset with annotations
  -> Paginator 50
  -> templates/backoffice/orders/order_list.html
```

Detail uses `select_related` and `prefetch_related` for cashier, opening entry, items/item groups, payments/modes, and KOTs. The detail template exposes cancellation and return controls depending on state and role.

## Manager Cancellation

```text
Cancel form
  -> POST orders:order_cancel
  -> orders.views.order_cancel()
  -> require manager/admin/superuser
  -> POSOrderCancelForm validation
  -> orders.services.cancel_order()
  -> order lock, stock reversal/reservation release, cancellation KOTs
  -> commit
  -> services.dispatch_tickets()
  -> redirect order detail with pending-print warnings
```

Paid submitted orders are rejected and preserve their original data. Sent draft orders are the cancellable kind — cancel releases drink reservations and creates cancellation KOTs; a submitted (paid) order that was cancelled earlier restores drink stock through reversal SLEs. Existing payments are not deleted. An unsent draft is never cancelled; the backoffice deletes it instead (`orders.views.order_delete`, manager-only).

## Return Creation and Submission

`orders.views.order_return()` checks manager/admin/superuser and calls `make_return()`. The service locks the paid submitted source, rejects an existing active return, clones each line with negative quantity and `return_against_item`, assigns an order number, recalculates a negative total, and creates `RETURN_CREATED`.

The resulting return is a draft; `settle_order()` rejects returns. Managers can reduce qty, drop lines, or mark drink lines as wastage on the draft (`order_return_line_update`). `orders.views.order_return_submit()` (manager-only) calls `submit_return()`, which re-validates each line, restores drink stock with `POS Return` SLEs (skipping wastage lines), writes proportional negative refund payment rows, and marks the return `SUBMITTED` with the `RETURN_SUBMITTED` audit event. The detail page shows "Submit return" and "Delete draft" for a return draft.

## KOT Register

`kot_list()` filters KOT type, ticket type, lifecycle status, print status, and order/KOT number. `kot_detail()` loads the source order, production unit, creator, and item snapshots. Neither view has an additional role check beyond the backoffice middleware.

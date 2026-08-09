# State Machines

## Orders

```mermaid
stateDiagram-v2
    [*] --> DRAFT: create_draft_order
    DRAFT --> SUBMITTED: settle_order
    DRAFT --> CANCELLED: cancel_order / cancel_sent_order
    DRAFT --> DISCARDED: discard_order
    SUBMITTED --> CANCELLED: cancel_order if unpaid
    SUBMITTED --> DRAFT: make_return creates a new return draft
    CANCELLED --> [*]
    DISCARDED --> [*]
```

- `Order.save()` blocks direct lifecycle changes and the services use `_transition()` flags for the intended transition.
- Paid submitted orders cannot be cancelled; `make_return()` creates a separate negative draft instead.
- Discard requires an empty, unprinted, unsent, unpaid draft.
- `DRAFT` editing also stops after a KOT or receipt claim.

## KOT and BOT

```mermaid
stateDiagram-v2
    [*] --> PENDING: create_tickets
    PENDING --> PRINTED: dispatch_tickets success
    PENDING --> PENDING: dispatch_tickets failure
    PENDING --> CANCELLED: cancel order cancels source ticket
    PRINTED --> CANCELLED: cancel order cancels source ticket
    PRINTED --> PRINTED: manager reprint
```

The KOT `status` (`SUBMITTED`/`CANCELLED`) and `print_status` (`PENDING`/`PRINTED`/`CANCELLED`) are separate. Cancellation tickets are new submitted KOT rows and can independently be retried. `KOT_PRINT_CANCELLED` exists as a choice but no inspected workflow sets it.

## Shifts

```mermaid
stateDiagram-v2
    [*] --> OpeningDraft: backoffice draft creation
    OpeningDraft --> Open: submit / open_shift
    OpeningDraft --> Cancelled: cancel with no orders
    Open --> Closed: submit_closing_entry
    Open --> Cancelled: opening cancel with no orders
    Closed --> ClosingCancelled: cancel closing entry if no newer open shift
```

- `POSOpeningEntry.status` remains `SUBMITTED` after close; `closing_entry_id` distinguishes open from closed.
- Opening submission is serialized by locking the `Restaurant` row and open shift rows.
- Cancelling a closing entry does not reopen the opening entry.

## Inventory Documents

`StockEntry`, `StockReconciliation`, and `PurchaseReceipt` use `DRAFT -> SUBMITTED -> CANCELLED`. Submission creates SLE rows. Cancellation creates reverse SLE rows and marks source SLEs cancelled. A service call on a non-draft/non-submitted document is generally idempotent and returns the current status.

## Invalid Transitions to Watch

- `settle_order()` rejects cancelled, submitted, empty, return, or no-active-shift orders.
- `cancel_order()` rejects discarded orders and paid submitted orders.
- `Order.delete()` rejects non-drafts, printed drafts, sent drafts, and audited rows may also be blocked by `OrderAuditEvent.PROTECT`.
- Inventory model saves can permit direct draft status flips without posting; use service paths when tracing actual ledger behavior.

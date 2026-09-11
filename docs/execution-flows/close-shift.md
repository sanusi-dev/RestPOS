# Execution Flow: Close Shift

## POS GET Preview

```text
Close shift navigation
  -> templates/pos/base.html
  -> GET pos:pos_close_shift (/pos/close-shift/)
  -> views_pos.pos_close_shift()
  -> _get_open_shift()
  -> Order.objects.open_drafts()
  -> staff.services.expected_closing_amounts()
  -> templates/pos/close_shift.html#surface
```

GET never creates closing rows. It renders a client-side count preview. If drafts remain, it returns the blocking "Finish open orders first" surface.

## POS POST Submission

```text
Counted amount form
  -> hx-post pos:pos_close_shift
  -> views_pos.pos_close_shift()
  -> atomic block and lock POSOpeningEntry
  -> recheck open drafts
  -> staff.services.ensure_closing_draft()
  -> ClosingPaymentForm per opening mode
  -> save counted values and closing period
  -> staff.services.submit_closing_entry()
  -> lock POSClosingEntry and POSOpeningEntry
  -> aggregate orders/payments
  -> calculate differences
  -> submit closing and link opening
  -> HX home surface or redirect
```

`submit_closing_entry()` recalculates the authoritative period end at submission. It includes submitted non-return orders in the period and computes expected values from opening balances plus payments minus cash change and minus submitted-return refunds in the period. It writes the frozen sales fields (`bill_count`, `total_quantity`, `net_total`, `grand_total`, `refunded_total`) and `total_short_excess`, marks the close submitted, and sets `opening_entry.closing_entry`.

## Rollback and Error Behavior

The POST transaction rolls back model changes from the current request if an exception escapes. Invalid forms can nevertheless leave a committed draft closing entry because `ensure_closing_draft()` runs before bound-form validation finishes. A later retry reuses that draft.

## Backoffice Variant

`staff.views.closing_entry_create()` locks the open shift and creates/reuses a draft. `closing_entry_detail()` edits counted values. `closing_entry_submit()` calls `full_clean()` and the same closing service. `POSClosingEntry.cancel()` only cancels the close; it does not reopen the shift.

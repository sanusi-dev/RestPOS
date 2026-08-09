# Execution Flow: Make Payment

## Dialog Load

```text
Pay link
  -> hx-get pos:pos_order_settle
  -> views_pos.pos_order_settle(GET)
  -> _get_settle_payment_modes()
  -> render pos/index.html#payment_dialog
  -> swap #payment-dialog-container
  -> Alpine posModalDialog initializes focus/close state
```

The GET does not settle or mutate data. It lists enabled modes with a non-null mapping and non-empty mapping account.

## POST

The dialog sends fields named `payment_<mode_id>` and optional `reference_<mode_id>`. The view drops blank values and passes a list of dictionaries to `settle_order()`.

`_validate_payment_data()` resolves each mode, checks enabled/opening declaration/GL mapping, normalizes references, enforces two-decimal finite amounts, and discards zero rows. At least one positive row is required.

`settle_order()` locks the order, recalculates the rounded total, validates active shift/stock, creates `OrderPayment` rows, sets `paid_amount`, `change_amount`, `is_paid`, `status=SUBMITTED`, and `submitted_at`, then converts drink reservations to actual stock issues.

## Frontend Result

Success clears `pos_order_id` and that order's active-card session entry, shows a message, and redirects to `pos_home`. Validation shows a Django message and redirects back to the order screen; the payment dialog itself is not re-rendered with bound errors.

## Failure Tracing

If the mode is visible but settlement rejects it, compare the global enabled/mapped set used by `_get_settle_payment_modes()` with the opening mode IDs required by `_validate_payment_data()`. If payment exists but the order is still draft, inspect transaction rollback and any validation after payment creation.

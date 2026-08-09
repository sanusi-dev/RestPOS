# Payment Workflow

## Payment Layers

The `payments` app owns payment master data only:

- `ModeOfPayment`: name, type (`CASH`, `BANK`, `GENERAL`, `PHONE`), enabled flag, and default flag.
- `PaymentGLMapping`: one-to-one mapping to a non-empty account name.

Sale payment rows are `orders.OrderPayment`, linked to an Order and ModeOfPayment. There is no external payment gateway, refund model, or separate payment-entry document.

## Configuration

`ModeOfPayment` has a conditional unique constraint allowing at most one default. Its `clean()` and `save()` prevent unsetting the only default. Payment views/forms provide login-protected CRUD. GL mapping deletion is POST-only; other ordinary form saves do not use an explicit service transaction.

## Shift Opening

`OpeningFloatForm` dynamically creates one non-negative Decimal field per enabled mode. `open_shift()` creates one `OpeningPayment` per submitted mode. Opening does not require GL mappings, although settlement later does.

## Settlement

The POS dialog is GET `/pos/order/<pk>/settle/`; POST extracts `payment_<mode_pk>` and `reference_<mode_pk>` fields. `settle_order()` validates:

- at least one positive payment;
- finite two-decimal amount;
- enabled mode;
- mode declared at shift opening;
- existing non-empty GL mapping;
- reference length <= 100;
- full coverage of rounded order total.

Electronic reference numbers are unique per payment mode when non-empty. Cash references are not duplicate-checked.

Cash may exceed the total and produces `Order.change_amount`. Any overpayment containing a non-cash row is rejected. Underpayment is rejected. Payments are created inside the settlement transaction, and pre-existing payment rows cause manager review validation.

## Shift Closing

`staff.services.expected_closing_amounts()` sums submitted order payments in the period and subtracts `Order.change_amount` for cash orders. The result is opening float plus net collected amount. `submit_closing_entry()` stores expected, counted, difference, and total short/excess values.

## Current Non-Features

- No partial payment or outstanding balance: settlement requires full payment.
- No discounts or write-offs: order totals are line sum plus whole-unit rounding.
- No refund/void service: paid returns cannot be submitted.
- No payment provider integration: all electronic modes are manual records with optional references.

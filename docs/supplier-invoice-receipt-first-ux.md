# Plan: Receipt-first supplier invoice UX with dedicated expense lines

Status: **Agreed — ready to build.**

## Objective

Redesign the supplier invoice flow so an invoice is **generated from the linked purchase receipt**:

- The user only inputs invoice header fields (supplier, posting/due date, bill no., bill date, remarks) and an **expense line formset** (description + amount only).
- Stock lines are **not user input**: on submit, the service creates `SupplierInvoiceItem` rows from the submitted receipt's `PurchaseReceiptItem` rows, and they are read-only thereafter.
- Expense lines become a dedicated model `SupplierInvoiceExpense` (description + amount), posting Dr Default Expense Account / Cr Payable. The account comes from a new `Restaurant.default_supplier_expense_account` setting; a missing configuration is a hard error at submit.
- **Pre-production:** no data-preserving migration. The existing `SupplierInvoiceItem` table is dropped and recreated without the `item`/`expense_account`/manual-qty-rate type-switch surface.

## Why this shape (and the one deviation from the user's wording)

ERPNext's `Purchase Receipt → Create → Purchase Invoice` mapper (`references/erpnext-develop/erpnext/stock/doctype/purchase_receipt/mapper.py::make_purchase_invoice`) is the same flow: receipt lines map into invoice lines with qty/rate coming from the receipt. We adopt that, plus the user's expense-line simplification.

The user suggested "maybe a dedicated model for receipt expenses" — implemented as **two dedicated models** (`SupplierInvoiceItem` = stock lines only, `SupplierInvoiceExpense` = expense lines only) instead of one type-switched model. The two have genuinely different lifecycles (service-created read-only vs user-editable draft lines), and splitting removes the type-guard logic and the stock-line formset entirely.

## Phase 1 — Models

### `apps/settings/models.py`

Add to `Restaurant` (in the Payables section):

```python
default_supplier_expense_account = models.ForeignKey(
    "accounting.LedgerAccount",
    on_delete=models.PROTECT,
    null=True,
    blank=True,
    related_name="+",
    verbose_name="Default supplier expense account",
    help_text="Expense account debited by supplier invoice expense lines.",
)
```

`Restaurant.load()` does not need to select_related it (services fetch accounts via helper already).

### `apps/accounting/payables_models.py`

- **`SupplierInvoiceItem`** — becomes stock-lines-only:
  - Remove fields: `expense_account`.
  - Remove `clean()` / `validate_for_submission()` type-switch logic (item vs expense branches).
  - `clean()`: keep only item eligibility guard (`item` must be enabled, stock, purchase item) and the receipt-link guard (stock line on a receipt-linked invoice must link to a receipt line; the linked receipt must be SUBMITTED; supplier must match; no duplicate receipt-line link).
  - `save()`: keep `item`/`qty`/`rate`/`received_qty`/`amount_per_unit`/`description` auto-fill from the receipt line; drop the now-unreachable manual-rate path (`rate is None` default remains for safety).
  - `validate_for_submission()`: keep the same guards as `clean()` (used by `submit()`).
  - `__str__` stays.

- **`SupplierInvoiceExpense`** (new) — description + amount only:

  ```python
  class SupplierInvoiceExpense(BaseModel):
      """A supplier invoice expense line — a non-stock cost with a description and amount."""
      invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name="expenses")
      description = models.CharField(max_length=200)
      amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
  ```

  - `clean()`: require non-empty description; `amount > 0` (else `ValidationError({"amount": ...})`).
  - `save()`: quantize amount to 2dp; `full_clean()`.
  - `delete()`: draft-only guard (mirror `SupplierInvoiceItem.delete()`).
  - Meta: `ordering = ["pk"]`.

- **`SupplierInvoice`** — unchanged except:
  - `submit()`: build stock lines from receipt items before validation (see Phase 3 service); validate stock lines + expense lines; totals include expense amounts.
  - `cancel()` unchanged.

### `apps/accounting/models.py`

Update the payables import block: `SupplierInvoiceItem` stays, add `SupplierInvoiceExpense`.

## Phase 2 — Forms

### `apps/accounting/payables_forms.py`

- **Delete `SupplierInvoiceItemForm` and `SupplierInvoiceItemFormSet`** (stock lines are no longer user input).
- **`SupplierInvoiceForm`**: unchanged fields (supplier, posting_date, due_date, bill_no, bill_date, purchase_receipt, remarks) + receipt-supplier cross-validation.
- **New `SupplierInvoiceExpenseForm`** — Meta fields `["description", "amount"]`; both required; styled.
- **New `SupplierInvoiceExpenseFormSet`** = `inlineformset_factory(SupplierInvoice, SupplierInvoiceExpense, form=SupplierInvoiceExpenseForm, extra=1, can_delete=True)`.

## Phase 3 — Service (`apps/accounting/services.py`)

### New: `build_supplier_invoice_stock_lines(invoice)`

- Requires `invoice.purchase_receipt_id` when the receipt has stock items (GRNI clearing needs a receipt).
- Iterates `invoice.purchase_receipt.items.all()`; for each `PurchaseReceiptItem` not already linked to a `SupplierInvoiceItem` on this invoice, creates:

  ```text
  SupplierInvoiceItem(invoice=invoice, item=item, source_receipt_line=line, qty=line.received_qty, rate=line.rate, ...)
  ```

  (`save()` auto-fills item/qty/rate anyway; the explicit values make the intent clear.)
- Error on item not enabled/stock/purchase-item, or a duplicate receipt-line link.

### `post_supplier_invoice_gl(invoice)` — restructure

- Stock leg: iterate `invoice.items` (now stock-only). Each row: `Dr settings.stock_received_but_not_billed_account / Cr payable`, amount = `line.amount`. Requires `invoice.purchase_receipt_id` and the rate-lock (`line.qty == line.source_receipt_line.received_qty and line.rate == line.source_receipt_line.rate`) — keep the existing conditional enforcement.
- Expense leg: iterate `invoice.expenses`:

  ```python
  account = settings.default_supplier_expense_account
  account = _resolve_required_account(account, label="The default supplier expense account")
  expense_total += expense.amount
  expense_rows.append({"account": account, "debit": expense.amount})
  ```

- Single payable credit = stock_total + expense_total; `_merge_rows` handles same-account consolidation. Idempotency guard and `GLEntry.post` unchanged.

### `SupplierInvoice.submit()` (in `payables_models.py`) — integrate

```python
build_supplier_invoice_stock_lines(locked)
lines = list(locked.items.select_related("item", "source_receipt_line"))
expenses = list(locked.expenses.all())
if not lines and not expenses:
    raise ValidationError("Add at least one line before submitting.")
total = Decimal("0")
for line in lines:
    line.validate_for_submission()
    total += line.amount
for expense in expenses:
    expense.full_clean()
    total += expense.amount
locked.total = total
...
```

(Import `build_supplier_invoice_stock_lines` locally inside `submit()` to avoid a circular import — same pattern as the existing `from .services import post_supplier_invoice_gl`.)

## Phase 4 — Views (`apps/accounting/payables_views.py`)

- `supplier_invoice_create` / `supplier_invoice_update`:
  - Replace `item_formset` with `expense_formset` (`SupplierInvoiceExpenseFormSet`).
  - Render `{"form", "is_create", "expense_formset", "show_errors"}`.
  - POST: `form.is_valid() and expense_formset.is_valid()` → `invoice = form.save(); expense_formset.instance = invoice; expense_formset.save()`.
- Delete `supplier_invoice_item_add` / `supplier_invoice_item_remove`; add `supplier_invoice_expense_add` / `supplier_invoice_expense_remove` using `add_formset_row` / `remove_formset_row` with the new formset, rendering the `#expenses-partial` partial.
- `supplier_invoice_detail`: fetch `invoice.items` (stock) + `invoice.expenses`; context gets both.

## Phase 5 — Templates

### `supplier_invoice_form.html` — restructure

- Header copy: "Item lines come from the linked purchase receipt; expense lines are entered here."
- Keep the header form card (`form` fields).
- **Receipt preview panel** (read-only, appears when a receipt is selected): supplier, posting date, receipt number, and a table of the receipt's stock lines (item, qty, rate, amount) with a caption "Item lines will be generated from this receipt on save."
- **Expense lines partial** (`{% partialdef expenses_partial inline %}`): card titled "Expenses"; `expense_formset.management_form`; table with Description / Amount / delete; "+ Add Expense" button posting to `supplier_invoice_expense_add`; the container `id="supplier-invoice-expenses-container"` swapped via HTMX (no stock-line table in the formset anymore).
- Footer: Create Draft / Save Changes button.

### `supplier_invoice_detail.html` — show both line groups

- Stock lines table (from receipt, read-only).
- Expense lines table (description, amount, total).
- GL entries unchanged.

## Phase 6 — Migrations

- `uv run python manage.py makemigrations` then review generated files.
- Migration 1 (`settings`): add `Restaurant.default_supplier_expense_account`.
- Migration 2 (`accounting`): remove `SupplierInvoiceItem.expense_account`; add `SupplierInvoiceExpense`; drop the old `SupplierInvoiceItemForm`-era data (pre-production — no RunPython data preservation).
- `uv run python manage.py migrate`.

## Phase 7 — Tests (`apps/accounting/tests/test_payables.py`)

- Update `_add_expense_line` → `SupplierInvoiceExpense.objects.create(invoice=invoice, description="Cleaning", amount=amount)`; remove `_add_stock_line` (no manual stock-line creation in tests — stock lines come from receipt via submit).
- Keep D4 rate-lock tests, reworked:
  - `test_submit_generates_stock_lines_from_receipt`: create submitted receipt with 2 items → submit invoice → assert 2 `SupplierInvoiceItem` rows, amounts = receipt amounts, GL has GRNI debit + payable credit.
  - `test_stock_line_on_receipt_invoice_requires_receipt_link` → direct-creation of a stock line without link on a receipt-linked invoice raises.
  - `test_stock_line_autofills_qty_rate_from_receipt_line` → direct creation auto-fills.
- Update `_paid_invoice` helper (stock invoice from receipt).
- Update `test_submit_posts_stock_and_payable_legs`, `test_submit_fails_closed_without_payable_account`, `test_submit_uses_supplier_payable_override`, `test_submit_uses_receipt_line_source`, `test_cancel_reverses_gl_and_clears_outstanding`, `test_cancel_twice_is_idempotent` — stock lines generated from receipt instead of manually created.
- `test_submit_posts_expense_and_payable_legs`: expense now posts to `restaurant.default_supplier_expense_account` (set it in the base/test); assert Dr default-supplier-expense / Cr payable.
- New: `test_submit_fails_without_default_supplier_expense_account` (expense line, account unset → error "default supplier expense account", stays DRAFT).
- Run: `uv run python manage.py test apps.accounting --keepdb --noinput`.

## Phase 8 — Verify

- `uv run python manage.py test apps.accounting apps.inventory apps.orders apps.reports apps.settings apps.web --keepdb --noinput` (full suite).
- `make ruff-lint` and `make npm-type-check` (JS untouched, but confirm no breakage).
- Browser-verify the invoice create/update/detail flows (form → expense add/remove → submit → detail shows stock + expense lines → cancel) if the user wants browser verification; otherwise tests + curl.
- Update `docs/` if it references the old invoice-item formset / manual stock-line entry.
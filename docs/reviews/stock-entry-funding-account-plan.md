# Plan — Market stock receipt credits the selected payment mode's GL account

> **Status:** draft — for review, not yet agreed or implemented.
> **Branch:** feat/uom-conversion
> **Date:** 2026-09-07

## Context

A `StockEntry` with purpose `MATERIAL_RECEIPT` is the informal market purchase: stock bought
on the spot from the market, no supplier, no invoice, no payables. It is still a **stock**
receipt — the goods land in the central Store bin, blend the Store's WAC, and create SLEs.
Only the funding credit is wrong today.

### Current behavior

On submit, `submit_stock_entry()` posts:

```
Dr  Stock in Hand (Store warehouse account)
Cr  Restaurant.default_expense_account (COGS)
```

(`apps/inventory/services.py`, receipt branch). The code comment says "market purchase, no GRNI".
This mirrors ERPNext's non-perpetual "expense at receipt" shortcut, which contradicts this
system's perpetual-WAC design:

- Selling the stock later posts `Dr COGS / Cr SIH` at WAC into the **same** COGS account
  (`apps/accounting/services.py`, `_cogs_legs()`). The purchase credit and the sale debit
  cancel, so the cost of market-bought stock never appears on the P&L.
- Cash is never credited, so the drawer/shift reconciliation drifts: money taken from the
  till to buy stock leaves no GL trace on the cash account.

### Required behavior

- Material Receipt of stock items posts:
  ```
  Dr  Stock in Hand (Store warehouse account)
  Cr  <GL account mapped to the payment mode chosen on the form>
  ```
- Cancellation of a receipt reverses both GL legs (including the funding account) via the
  original GL rows; the existing `CANCELLATION_WAC` drift-to-variance logic stays.
- Funding accounts come only from the existing chain
  `ModeOfPayment → PaymentGLMapping → default_account`
  (`apps/payments/models.py`), resolved with the same helper and rules orders use
  (`apps/accounting/services.py`, `_resolve_payment_account`): the mode must be enabled, its
  mapping present, and the mapped account enabled and a leaf.

## Decisions (confirmed)

| # | Decision |
|---|---|
| D1 | Material Receipt credit = the account mapped to the payment mode selected on the receipt form ("Paid from"). One funding source per receipt header. |
| D2 | Offered modes = all enabled payment modes, validated exactly like POS (`_resolve_payment_account`). |

## Changes

### 1. Model — `apps/inventory/models.py`

Add to `StockEntry`:

```python
mode_of_payment = models.ForeignKey(
    "payments.ModeOfPayment",
    null=True,
    blank=True,
    on_delete=models.PROTECT,
    related_name="stock_entries",
)
```

- Not required at model level (transfers have none; a draft receipt may not have one yet).
- `on_delete=PROTECT` so a mode used by submitted entries cannot be deleted/disabled
  silently.

### 2. Validation — service or `clean()`

- Receipt: `mode_of_payment` required at submit, enabled, mapping present, mapped account
  enabled and leaf.
- Transfer: `mode_of_payment` must be `None`.

### 3. Form — `apps/inventory/forms.py`

`StockEntryForm`:

- Add `mode_of_payment` to fields.
- Queryset = enabled modes only.
- Hide/disable on `MATERIAL_TRANSFER`; required on `MATERIAL_RECEIPT` (form-level when the
  purpose is known).

### 4. Posting — `apps/inventory/services.py`

Replace the receipt GL leg in `submit_stock_entry()`:

```python
# Current:
expense_acct = _resolve_account(default_expense, "The default expense account")
gl_rows.append({"account": sih_account, "debit": amount})
gl_rows.append({"account": expense_acct, "credit": amount})

# New:
funding_acct = _resolve_payment_account(locked.mode_of_payment)
gl_rows.append({"account": sih_account, "debit": amount})
gl_rows.append({"account": funding_acct, "credit": amount})
```

`default_expense` no longer needed for the receipt leg; drop the local if unused.

**Cancellation** (`cancel_stock_entry()`, receipt branch): currently reverses
`Cr SIH @ current / Dr expense @ original` with drift to the variance account. Rework to
mirror the original non-cancelled `GLEntry` rows for this voucher (swap debit/credit), so the
funding account reverses correctly. Full cancel of a straight receipt without WAC drift nets
zero with no variance; drift still posts `CANCELLATION_WAC` to
`inventory_price_variance_account` when WAC moved between receipt and cancel.

### 5. UI

- `stock_entry_form.html`: "Paid from" field in the Entry details section, shown only when
  `purpose === 'MATERIAL_RECEIPT'` (existing Alpine `purpose` binding, mirroring how
  `basic_rate` hides on transfers).
- `stock_entry_list.html` / `stock_entry_detail.html`: show the mode (name + mapped account)
  for submitted receipts so they are auditable.

### 6. Tests — `apps/inventory/tests/test_stock_entry.py`

- Receipt with a mapped cash mode posts `Dr SIH / Cr cash` (accounts + amounts).
- Receipt without a mode → validation error; disabled mode / unmapped mode → error.
- Transfer with a mode → validation error; transfer posts no GL.
- Cancellation reverses both legs, zero variance when WAC unchanged; variance drift when WAC
  moved; funding account credited/debited correctly.
- Update tests that assert the old `Cr expense` behavior.

### 7. Docs

- `FEATURES.md` #15 and #61: "market purchase posts Dr SIH / Cr expense" →
  "Dr SIH / Cr the GL account mapped to the selected payment mode".
- `docs/workflows/inventory.md`: update the Stock Entry section and the "every inventory
  mutation" table; note cancellations reverse via the original GL rows (funding account
  included).
- `PLAN.md` §4.9: amend the market-purchase GL line (D4/GL-entries block) to
  "Dr SIH / Cr payment-mode account"; per the PLAN protocol, add this as a final agreed-plan
  amendment once approved.

## Edge cases

- Multiple receipt lines, one mode → one merged credit (existing `_post_gl_rows` merge).
- Zero-amount lines → existing skip; mode still required at header.
- Draft edited after choosing a mode → no GL yet; existing post-submit edit blocks apply.
- Mode disabled after submission → history unaffected (`PROTECT`); new drafts must pick an
  enabled mode.
- Receipt cancel with downstream docs → stock-entry receipts never link invoices; D6 block
  does not apply.

## Open items (reviewer)

1. Header-level mode (one funding source per receipt) vs per-line — header recommended.
2. Whether the seed/chart needs a note that all enabled modes should carry mappings
   (existing `seed_chart_of_accounts` already wires them).
3. Wording of the PLAN.md/FEATURES.md amendment once approved.

## Build order

1. Model FK + migration.
2. Form field + purpose-conditional visibility; template field.
3. Service: receipt credit swap; cancellation mirror of original GL rows.
4. Tests.
5. Docs (FEATURES, workflow doc, PLAN amendment).

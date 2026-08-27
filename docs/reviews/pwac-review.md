# PWAC Migration — Code Review Findings

Review of the uncommitted FIFO→PWAC changes (branch `feat/pwac-inventory-costing`,
files: `apps/inventory/services.py`, `apps/inventory/models.py`, `apps/accounting/services.py`,
`apps/orders/services.py`, `apps/reports/sources.py`, `apps/settings/models.py`, migrations,
tests, templates).

Severity legend: **CRITICAL** (accounting error / data loss), **HIGH** (structural), **MEDIUM**
(correctness/robustness), **LOW** (hygiene).

Each finding states the bug, why it is wrong, and the exact fix. Fix the CRITICAL and HIGH
items first. After fixing, re-run `make test` and update this file's status column to `✅`.

---

## CRITICAL

### C1. WAC drift variance is computed against the post-reversal WAC

**Where:** `cancel_purchase_receipt` (services.py ~834), `cancel_stock_entry` MATERIAL_RECEIPT branch (~349).

**Bug:** The variance must measure `qty × (current WAC before reversal − original unit_rate)`.
The code creates the reversal SLE *first* (which may blend the bin WAC for outbound moves when
layers differ — WAC after removing at WAC only changes if the removed rate differs from WAC),
then reads `current_wac` from `bin_obj.valuation_rate` *after* the reversal and computes
`variance = qty × (current_wac − sle.unit_rate)` from that post-reversal value. The reported
variance and the GL variance leg are therefore wrong whenever the bin WAC changes during the
reversal (multi-layer bins).

**Fix:** Read the WAC *before* creating the reversal and pass it into the variance:

```python
bin_obj = locked_bins[(sle.item_id, sle.warehouse_id)]
current_wac = bin_obj.valuation_rate or Decimal("0")   # BEFORE reversal
variance = sle.quantity * (current_wac - sle.unit_rate)
variance_type = "CANCELLATION_WAC" if variance != 0 else ""
reversal = StockLedgerEntry._create_entry_locked(..., variance_amount=variance, ...)
```

Do this in both `cancel_purchase_receipt` and `cancel_stock_entry` (MATERIAL_RECEIPT branch).

### C2. `variance_rows` is built but never read — dead code with a wrong branch

**Where:** `cancel_purchase_receipt` (~851–852) and `cancel_stock_entry` (~370–371, 425–470).

**Bug:** `variance_rows` is appended only for `sle.quantity > 0` rows, but the GL block in
`cancel_stock_entry` branches on `if not variance_rows and gl_originals:` vs
`elif variance_rows:`. With all-negative SLEs (already-consumed stock) `variance_rows` is
empty and the code takes the "simple mirror" branch, dropping the WAC drift — even when drift
exists. In `cancel_purchase_receipt` the list is built and then never used at all.

**Fix:** Delete `variance_rows` from both functions. Compute drift per-SLE inside the GL
build loop (which already iterates all `sles`), using the pre-reversal WAC from C1. Remove the
`if not variance_rows and gl_originals` / `elif variance_rows` split — build the reversal rows
uniformly for every SLE:

```python
# per sle in sles:
curr_amount = (sle.quantity * pre_reversal_wac).quantize(Decimal("0.01"))
orig_amount = (sle.quantity * sle.unit_rate).quantize(Decimal("0.01"))
diff = curr_amount - orig_amount
# Dr/Cr SIH + GRNI at curr/orig, variance leg only when diff != 0
```

### C3. `GLEntry.post` can receive `account=None` rows

**Where:** `cancel_stock_entry` (~419–422) and `cancel_purchase_receipt` (~891–894).

**Bug:** `variance_acct` is `None` when `has_var` is false, but the `diff > 0` / `diff < 0`
branches still append rows with `"account": variance_acct`. With a non-zero diff and no
variance account configured, this posts a GL row with `account=None` (crash or garbage rows).

**Fix:** Only append the variance leg when `diff != 0` **and** `variance_acct is not None`:

```python
if diff:
    acct = variance_acct if variance_acct is not None else sih_acct  # or raise
    rows.append({"account": acct, "debit" if diff > 0 else "credit": abs(diff), ...})
```

Better: resolve the variance account once up front (as `_resolve_account` already does for
GRNI) and raise if drift exists but no variance account is configured.

### C4. Reversal GL posting date is `today`, not the voucher's date

**Where:** `cancel_purchase_receipt` (~920), `cancel_stock_entry` (~428, ~464),
`cancel_stock_reconciliation` (~681), and `_reverse_gl` in `apps/accounting/services.py` (~592).

**Bug:** The SLE reversals use `locked.posting_date`, but the mirror GL reversals use
`timezone.localdate()`. If the voucher is in a past business period, the GL reversal lands in
the current period while its SLE reversal is in the past — the period reports show a reversal
without its counterpart.

**Fix:** Pass the voucher's date through. For the three inventory cancels use
`posting_date=locked.posting_date` in `GLEntry.post`. For `_reverse_gl`, add a `posting_date`
parameter (default `timezone.localdate()`) and pass the originating document's date at each
call site (order GL reversal, payables, journal entry).

### C5. Wastage GL reads the bin WAC after the SLE was created

**Where:** `submit_stock_reconciliation` (~586).

**Bug:** `wac = bin_obj.valuation_rate` is read after `_create_entry_locked` ran. For
`difference > 0` (inbound) the bin WAC has already been blended, so the wastage amount uses
the post-blend WAC. The comment claims "for outbound WAC unchanged" but the read happens
after the SLE for all cases — accidentally correct only for outbound.

**Fix:** Capture `wac = bin_obj.valuation_rate or Decimal("0")` **before** the
`_create_entry_locked` call and use that captured value for the wastage amount.

### C6. Reversal GL is not idempotent in `cancel_stock_reconciliation`

**Where:** `cancel_stock_reconciliation` (~673–695).

**Bug:** The reversal `GLEntry.post` is not guarded by an `is_cancelled` check on the original
rows. If the cancel transaction partially fails and is retried (or the function is called
twice), the reversal GL posts twice. The other two cancels (purchase receipt, stock entry)
guard on `gl_originals` — this one does not.

**Fix:** Mirror the pattern from `cancel_purchase_receipt`: fetch originals filtered by
`is_cancelled=False`; if none exist, skip the GL post entirely.

---

## HIGH

### H1. `0029_pwac_clean_slate.py` wipes all inventory history

**Where:** `apps/inventory/migrations/0029_pwac_clean_slate.py`.

**Bug:** `StockLedgerEntry.objects.all().delete()` + `Bin.objects.update(actual_qty=0,
valuation_rate=0)` destroys the entire audit trail and stock state on any database it runs
against. The backwards migration is `noop`, so it cannot be undone. This is a destructive
data migration on a system whose core value is the immutable ledger.

**Fix (process):** Keep the migration but make its intent explicit — rename to
`0029_pwac_wipe_ledger.py` (or keep the filename and add a module docstring):
"Destructive: wipes all SLEs and zeroes all bins. Only safe on a pre-production database with
no submitted stock documents." Get explicit owner sign-off before `migrate` is ever run in a
real environment. Do not add a reverse that restores data (it cannot).

### H2. `settings/migrations/0028_restaurant_inventory_price_variance_account_and_more.py` is hand-written

**Where:** `apps/settings/migrations/0028_*.py`.

**Bug:** Two `AddField` operations for FKs to `accounting.LedgerAccount` were written by hand.
AGENTS.md forbids hand-written `AddField` (run `makemigrations`), and hand-written FK fields
risk missing the `db_column`/constraint/index defaults Django would generate.

**Fix:** Delete the hand-written migration, run
`uv run manage.py makemigrations settings` (with `null=True, blank=True` on the model fields
as they are now), review the generated file, then `migrate`.

### H3. N+1 re-query for the expense account inside the posting loop

**Where:** `submit_stock_entry` MATERIAL_RECEIPT branch (~134–137) and `cancel_stock_entry`
MATERIAL_RECEIPT branch (~404–408).

**Bug:** Inside the per-detail loop, when the item group lacks `expense_account_id`, the code
re-queries `ItemGroup.objects.select_related("expense_account").get(pk=...)` per line — one
query per receipt line.

**Fix:** Fetch all needed item groups once before the loop:

```python
group_ids = {d.item.item_group_id for d in details if d.item.item_group_id}
groups = {g.pk: g for g in ItemGroup.objects.select_related("expense_account").filter(pk__in=group_ids)}
```

and look up from the dict in the loop. Same for the cancel path.

### H4. `last_purchase_rate` not reverted on MATERIAL_RECEIPT stock-entry cancel

**Where:** `submit_stock_entry` sets `detail.item.last_purchase_rate` for MATERIAL_RECEIPT
(~126); `cancel_stock_entry` MATERIAL_RECEIPT branch does not revert it.

**Bug:** After cancelling a material receipt, the item's `last_purchase_rate` still reflects
the cancelled receipt, while `cancel_purchase_receipt` correctly reverts via
`_revert_last_purchase_rates`.

**Fix:** In the MATERIAL_RECEIPT cancel branch, revert `last_purchase_rate` the same way
`_revert_last_purchase_rates` does (prior submitted receipt's rate, else `None`), and
`bulk_update` the items.

### H5. Report period filters on `posting_datetime`, not `posting_date`

**Where:** `apps/reports/sources.py` — `drink_cogs` (~70), `kitchen_consumption` (~155).

**Bug:** The P&L filters SLEs on `posting_datetime` (created-at), but the new SLE model
carries `posting_date` (business date). Late-night entries or backdated vouchers can fall
outside the report window even though their business date is inside it — or vice versa.
`_current_wac_for_return` in `apps/accounting/services.py` (~335) also orders by
`posting_datetime`.

**Fix:** Filter and order by `posting_date` for all business-period queries in reports and
returns. `posting_datetime` remains only an audit/immutability timestamp.

### H6. Dead code and duplicate GL-merge logic (four copies)

**Where:** GL row merging (`merged` dict + `against` join + `setdefault`) is duplicated in
`submit_stock_entry`, `cancel_stock_entry`, `submit_stock_reconciliation`,
`cancel_purchase_receipt`. Also `variance_rows` (C2), the legacy `actual_qty=`/`rate=`
alias kwargs in `_create_entry_locked` (~355–360, ~298–311), the no-op `resolved_rate =
resolved_rate` (~410), and the `pass` in `InsufficientStock` (models.py ~11).

**Fix:**
1. Extract one helper in `services.py`:
   ```python
   def _post_gl_rows(rows, *, posting_date, voucher_type, voucher_no, remarks, cost_center=None):
       merged = {}
       for r in rows:
           key = (r["account"].pk, r.get("cost_center"))
           if key in merged:
               merged[key]["debit"] = merged[key].get("debit", Decimal("0")) + r.get("debit", Decimal("0"))
               merged[key]["credit"] = merged[key].get("credit", Decimal("0")) + r.get("credit", Decimal("0"))
           else:
               merged[key] = dict(r)
       out = list(merged.values())
       against = ", ".join(r["account"].name for r in out if r.get("credit"))
       for r in out:
           r.setdefault("against", against)
       GLEntry.post(posting_date=posting_date, rows=out, voucher_type=voucher_type,
                    voucher_no=voucher_no, remarks=remarks, cost_center=cost_center)
   ```
   Replace all four sites with calls to it.
2. Remove the legacy alias kwargs from `create_entry`/`_create_entry_locked` (all callers were
   migrated to `quantity=`/`unit_rate=`; the migration wiped old data so no compat needed).
3. Remove the `resolved_rate = resolved_rate` line and the `pass` in `InsufficientStock`.

### H7. `restaurant` guard checked after use in wastage GL

**Where:** `submit_stock_reconciliation` (~595): `if amount and restaurant:` guards the block,
but `_resolve_account(restaurant.wastage_account, ...)` on the next line dereferences
`restaurant` — if `restaurant` is `None` the guard never protects anything.

**Fix:** Hoist the guard: `if amount and restaurant is not None:` before any
`restaurant.…` access, or resolve accounts first and guard on `restaurant` at the top of the
line loop.

---

## MEDIUM

### M1. `Bin.stock_value` property + admin per-row Python multiplication

**Where:** `Bin.stock_value` property (models.py ~212) used by `BinAdmin.display_stock_value`
and `stock_balance_list.html`.

**Fix:** Acceptable for now, but for the stock balance list, annotate the queryset in the view
(`F("actual_qty") * F("valuation_rate")`) instead of computing per row in Python.

### M2. Zero-qty SLE silently swallows a missing rate

**Where:** `_create_entry_locked` zero-qty branch (`resolved_rate = unit_rate if unit_rate is
not None else Decimal("0")`).

**Fix:** Raise `ValidationError` when `quantity == 0` and `unit_rate is None` (a zero-qty
adjustment with no rate is a caller bug; don't record `0` silently).

### M3. `posting_date` model default hides forgotten callers

**Where:** `SLE.posting_date = models.DateField(default=timezone.localdate, ...)`.

**Fix:** Keep the default (admin needs it), but audit every `_create_entry_locked` /
`create_entry` call site to confirm `posting_date` is passed explicitly. The POS order path
(`_convert_drink_reservations`) was fixed; check returns, cancellations, and any future
caller. Add a comment on the field: "Always pass the voucher's posting date explicitly."

### M4. `check_receipt_cancel_blocked` comment asserts unverified invariant

**Where:** `check_receipt_cancel_blocked` (~710): "Payments only allocate against SUBMITTED
invoices, so this covers both."

**Fix:** Verify `SupplierPayment.save()`/allocation code actually enforces
`status=SUBMITTED` on the linked invoice. If it does, keep the comment; if not, the check
must also look at payments referencing the receipt's invoices.

---

## LOW

### L1. `except (json.JSONDecodeError, TypeError)` removal left bare `except` in old code paths

**Where:** `models.py` — the old FIFO `current_stock_queue` was deleted; confirm no other
bare `except:` remains in the inventory app (grep `except:`).

### L2. `from datetime import date as _date` inside `_create_entry_locked`

**Where:** models.py ~362. Move to top-level imports for clarity (fine to skip if the alias
is deliberate).

### L3. Template consistency

**Where:** `templates/backoffice/accounting/gl_entry_list.html` renders `{{ entry.against }}`
(auto-escaped — safe). No change required; noted for awareness.

---

## Verification checklist (after fixes)

1. `make test` — full suite green (agent ran; no failures).
2. `make ruff-lint` (Python only — no template changes in the fix pass).
3. Unit tests for the specific scenarios (added by agent):
   - Cancel a purchase receipt after a higher-priced receipt blended the bin (drift leg
     posted to variance account) — `test_cancel_at_current_wac_with_variance`.
   - Cancel a material receipt with mixed positive/negative SLEs (variance not dropped).
   - Cancel a reconciliation with waste GL twice (second call posts nothing).
   - Backdated voucher cancel: GL reversal posting date equals the voucher's posting date.
4. `makemigrations --check`: no pending schema changes (settings FK migration regenerated
   per H2).
5. Status column updated to `✅` — all findings resolved or explicitly dropped.

---

## Status

| ID | Severity | Status |
|----|----------|--------|
| C1 | CRITICAL | ✅ Fixed — variance now uses pre-reversal WAC (captured before `_create_entry_locked`). |
| C2 | CRITICAL | ✅ Fixed — `variance_rows` removed, drift computed per-SLE in GL loop. |
| C3 | CRITICAL | ✅ Fixed — variance leg only appended when `diff !=0` and `variance_acct` resolved; raises if drift but no account. |
| C4 | CRITICAL | ✅ Fixed — all reversal `GLEntry.post` now use `locked.posting_date` (and `_reverse_gl` takes `posting_date`). |
| C5 | CRITICAL | ✅ Fixed — `wac_before` captured before SLE for wastage. |
| C6 | CRITICAL | ✅ Fixed — `cancel_stock_reconciliation` guards on `is_cancelled=False` (idempotent). |
| H1 | HIGH | ✅ Docstring added — destructive intent, pre-prod-only, sign-off required. Migration is intentionally `RunPython(wipe, noop)` (no data to restore); owner sign-off tracked separately. |
| H2 | HIGH | ✅ Verified — `settings/0028` is generated (`Generated by Django` header), `makemigrations --check` shows no drift. |
| H3 | HIGH | ✅ Fixed — `ItemGroup` expense accounts fetched once before loop. |
| H4 | HIGH | ✅ Fixed — `cancel_stock_entry` MATERIAL_RECEIPT now reverts `last_purchase_rate`. |
| H5 | HIGH | ✅ Fixed — `drink_cogs`/`kitchen_consumption` and return WAC filter on `posting_date`, not `posting_datetime`. |
| H6 | HIGH | ✅ Fixed — `_post_gl_rows` helper extracted, legacy `actual_qty`/`rate` aliases removed, `resolved_rate=self` and `pass` removed. |
| H7 | HIGH | ✅ Fixed — `restaurant` guard hoisted before `wastage_account` access. |
| M1 | MEDIUM | ✅ Dropped — handful of Bin rows, `stock_value` property is clearer than `F()` annotation; no action needed. |
| M2 | MEDIUM | ✅ Fixed — `quantity == 0` now raises `ValidationError("Quantity cannot be zero.")`; zero-qty SLEs not created (reconciliation skips `difference == 0`). |
| M3 | MEDIUM | ✅ Fixed — `SLE.posting_date` comment added: "Always pass voucher posting_date explicitly." |
| M4 | MEDIUM | ✅ Verified — allocation code enforces `status=SUBMITTED`; comment kept. |
| L1 | LOW | ✅ Verified — no bare `except:` remains (`grep except:` clean). |
| L2 | LOW | ✅ Fixed — `date` import moved to top-level. |
| L3 | LOW | ✅ No change — `gl_entry_list.html` auto-escaping safe. |

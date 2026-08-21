

## Issue map

| ID | Severity | Master issue | Subsumes |
|----|----------|--------------|----------|
| 1 | P1 | No repost/rebuild: historical insertions unsupported | Bin/queue divergence with no repair, backdated docs in wrong FIFO position and wrong report period |
| 2 | P1 | SLE is not truly immutable | Direct-mutation desync of Bin and queue |
| 3 | P1 | Cancellation is current-state reversal, not chronological | Nondeterministic reversal order, layer-identity errors |
| 4 | P1 | Returns/cancellations restore stock as zero-rate layers | Understated COGS after returns |
| 5 | P2 | `prevent_negative` is opt-in | Negative-stock risk (restated) |
| 6 | P2 | Reconciliation positive corrections post at zero rate | FIFO dilution, understated transfers/COGS |
| 7 | P2 | Positive postings set `valuation_rate` to the incoming rate | Misstated Bin valuation and stock value |
| 8 | P3 | `stock_queue` is a manually-managed TextField with silent corruption fallback | Malformed JSON silently zero-rated |
| 9 | P3 | `Bin.reserved_qty` has no consistency check | Stale reservations |

---

## P1 — Data integrity blockers

### 1. No repost/rebuild: historical insertions corrupt FIFO; Bin/queue divergence is unrecoverable

- **Location:** `apps/inventory/models.py:248` (`posting_datetime` is `auto_now_add`), `models.py:326-339` (queue read from latest SLE by write order), `models.py:388-401` (Bin mirror). No rebuild/replay service exists anywhere in the repo.
- **Problem:** SLE ordering is write time, not document `posting_date`. A backdated receipt/transfer/reconciliation is appended to the *current* queue as if it happened now. Past SLE queue snapshots are never replayed and Bins are never recomputed. Backdated documents also land in the wrong report period because reports filter SLEs by `posting_datetime` (`reports/sources.py:90-112`).
- **Subsumes:** §14 High "no historical repost/rebuild"; §6/§15.12 "no repair command" (Bin and queue silently diverge with no in-system reconciliation); the backdated-FIFO and wrong-period consequences from the prior analysis; makes correct opening-stock backfill and missed-receipt correction impossible.
- **Direction:** order the ledger by document posting date (or add an explicit posting sequence), add a replay/repost service that recomputes queue snapshots and Bins after a historical insertion, and a health-check/rebuild management command that flags Bin vs ledger mismatches. Issue 3 (chronological cancellation) and Issue 8 (corruption detection) can reuse this replay/health-check machinery.
- **Test:** backdate a receipt after later movements; assert queue, Bin, and outgoing rates match a clean chronological replay.

### 2. SLE is not truly immutable

- **Location:** `StockLedgerEntry` (`apps/inventory/models.py:234-403`) — no overridden `save()`/`delete()`; `editable=False` is a form/admin restriction only.
- **Problem:** Admin, shell, or direct ORM `update()` can mutate or delete posted rows, desyncing Bin, queue, and `qty_after_transaction`. The bypass is acknowledged in `docs/database/transactions.md:46-48`.
- **Subsumes:** §14 High "SLE has no actual model-level immutability"; the direct-mutation divergence mechanism from the prior analysis; issue.md #3's save/delete-guard direction.
- **Direction:** override `save()`/`delete()` so posted SLEs are immutable except for `is_cancelled`, which only the reversal service may set; make admin read-only for posted rows.
- **Test:** attempt `update()`/`delete()` on a posted SLE; assert it is rejected.

### 3. Cancellation is current-state reversal, not chronological reversal

- **Location:** `_reverse_voucher()` (`apps/inventory/services.py:350-379`).
- **Problem:** Reversal posts an inverse movement against the *current* queue. It can consume layers the original movement never touched, its valuation depends on later movements, and it fails outright when stock has been consumed (tested at `test_purchase_receipt.py:76-121`). Reversal row order is also nondeterministic — the filtered queryset is converted to a list with no explicit ordering.
- **Subsumes:** §14 High "cancellation is current-state reversal"; §14 Medium "cancellation order is not explicitly deterministic"; the layer-identity errors of §4.3/§11. The insufficient-stock guard of §11 is intended protection — keep it, but reverse chronologically.
- **Direction:** reverse from the original SLE's own queue snapshot (chronological reversal) with explicit deterministic row ordering, reusing the Issue 1 replay machinery; retain the insufficient-stock protection.
- **Test:** cancel a receipt after later movements; assert the layer result matches removing the receipt chronologically.

### 4. Returns/cancellations restore stock as zero-rate FIFO layers

- **Location:** `_restore_stock()` (`apps/orders/services.py:1166-1191`) — calls `create_entry()` without a rate.
- **Problem:** Restored quantity appends a `[qty, 0]` layer; the source sale's outgoing cost is lost, so subsequent sales consume restored stock at zero cost and COGS is understated.
- **Subsumes:** §14 High "return/cancellation restoration can create zero-rate layers"; §7.3 valuation behavior.
- **Direction:** pass the original sale line's `outgoing_rate` (or the item's current valuation) as the restore incoming rate. Related to Issue 6, but a different call site and different correct rate — fixes are separate.
- **Test:** sale at rate X → return → sell again; assert the second sale's outgoing rate reflects X.

---

## P2 — Valuation and safety gaps

### 5. `prevent_negative` is opt-in: negative stock is a latent risk

- **Location:** `create_entry()` default `prevent_negative=False` (`apps/inventory/models.py:279`); check at `models.py:316-320`.
- **Problem (corrected per issue.md #3):** reconciliation **cannot** drive stock negative today — the service rejects negative counts and posts `counted − current ≥ 0`, so the ledger floors at zero. The real risk is the primitive: every current caller is safe only by opting in (`True` for settlements and transfers, `prevent_negative=sle.actual_qty > 0` for reversals). A future caller passing a negative `actual_qty` without the flag would silently drive the queue below zero with `outgoing_rate = 0` and a negative Bin valued at zero — no error, no traceback.
- **Subsumes:** §14 Medium "negative stock is possible on some paths" (restated accurately); issue.md #3.
- **Direction:** make `prevent_negative` required (keyword-only, no default) or default it to `True`, keeping `False` only where zero-fill is intentional.
- **Test:** a negative `create_entry()` call without the flag raises instead of posting.

### 6. Reconciliation positive corrections post at zero rate, diluting FIFO

- **Location:** `submit_stock_reconciliation()` (`apps/inventory/services.py:229-243`).
- **Problem:** Only `OPENING_STOCK` uses `line.valuation_rate`; every other purpose hardcodes rate zero, so a positive physical-count correction appends a `[qty, 0]` layer and the next outgoing movement consumes it at zero — transfers and COGS get understated (e.g. `[10 @ ₦1,000] + [5 @ ₦0]` → consuming 12 units costs ₦833.33/unit). The code comment claiming it "relies on the existing FIFO valuation" is inaccurate — it uses no existing valuation.
- **Subsumes:** issue.md #1; §14 Medium "reconciliation rate zero can create zero-cost layers".
- **Direction:** value positive corrections at `bin.valuation_rate` (current weighted average) or capture a unit cost on the reconciliation line.
- **Test:** count-up correction followed by a transfer; assert the FIFO rate equals the weighted average, not zero.

### 7. Positive postings set `valuation_rate` to the incoming rate, not the weighted average

- **Location:** positive branch of `_create_entry_locked()` (`apps/inventory/models.py:341-344`).
- **Problem:** `valuation_rate = rate` even when the queue still holds older layers at other rates; `stock_value = new_qty × rate` then misstates value until the next negative movement recomputes the weighted average. §12 example: `40 @100` + `50 @130` leaves the Bin at rate 130 while the true weighted rate is 116.67.
- **Subsumes:** §14 Medium "positive receipt valuation rate is not a weighted current rate".
- **Direction:** after appending a positive layer, compute the weighted average of the full queue as `valuation_rate`; `stock_value = new_qty × weighted rate`.
- **Test:** two receipts at different rates; assert Bin valuation and stock value equal the weighted figures.

---

## P3 — Hardening

### 8. `stock_queue` is a manually-managed TextField with a silent corruption fallback

- **Location:** `stock_queue = models.TextField` (`apps/inventory/models.py:258`); manual `json.dumps`/`json.loads` at `models.py:327-339` and `382`; silent `[]` fallback in `current_stock_queue()` (`models.py:225-231`) and `_create_entry_locked()` (`models.py:338-339`).
- **Problem:** Manual serialization, and malformed JSON is silently treated as an empty queue while the Bin still shows a nonzero balance — subsequent issues then post at `outgoing_rate = 0` with no error.
- **Subsumes:** issue.md #2; §14 Low "`current_stock_queue()` returns empty for malformed JSON".
- **Direction:** migrate to `JSONField(default=list)`, drop the manual parsing, and make corruption loud — raise or flag via the Issue 1 health check — instead of returning `[]`. (The existing unparenthesized `except ... TypeError:` is valid Python 3.14; the JSONField migration removes it anyway — do not "fix" its syntax separately.)
- **Test:** corrupt a queue row; assert posting fails loudly rather than silently zero-rating.

### 9. `Bin.reserved_qty` has no consistency check (stale reservations)

- **Location:** `reserve_drink_stock()` (`apps/orders/services.py:701-746`) and the release in `Order.delete()` (`apps/orders/models.py:252-271`) — `reserved_qty` changes with no ledger involvement.
- **Problem:** A lost draft order or a settlement crash between reservation and conversion can leave `reserved_qty` stale relative to actual stock, silently shrinking POS availability.
- **Subsumes:** the reservation-divergence mechanism from the prior analysis.
- **Direction:** add a health check/management command that recomputes `reserved_qty` from open draft orders. Reservations are not ledger state — the Issue 1 rebuild must not touch them.
- **Test:** abandon a draft order; assert reservations return to the open-order totals.

---

## Recommended solve order

1. P1 — issues 1 → 4 in order: repost/rebuild first (foundation), then immutability (stops new corruption), then cancellation and restore rates.
2. P2 — issues 5 → 7.
3. P3 — issues 8 → 9 (8 can reuse the Issue 1 health check).
4. After each fix: run the inventory and orders test suites, update the affected `/docs` pages and `inventory-stock-movement.md` where behavior changed, then re-run the full suite.

## Verification commands

```text
make test ARGS='--keepdb'
make ruff
make manage ARGS='makemigrations --check'
```

Do not modify anything under `references/`.

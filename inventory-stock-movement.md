# Inventory Stock Movement: Code-Level Trace

This report describes the inventory implementation in the repository as it exists. It is based on:

- `apps/inventory/models.py`
- `apps/inventory/services.py`
- `apps/inventory/views.py`
- `apps/inventory/forms.py`
- `apps/orders/services.py`
- `apps/orders/models.py`
- inventory tests under `apps/inventory/tests/`
- `docs/workflows/inventory.md`
- `docs/database/transactions.md`

The important conclusion is that there is **no separate `StockQueue` model**. The queue is serialized JSON stored on every `StockLedgerEntry` (SLE). `Bin` is the current-state snapshot. Source documents are the business records that request movement; they do not themselves contain the running stock balance.

## 1. Architecture

### 1.1 Components

| Component | Represents | Main implementation | Role and relationships |
|---|---|---|---|
| `Item` | A stockable/sellable material or product | `apps/inventory/models.py:100-186` | Defines `is_stock_item`, department, UOM, purchase/sales flags, and last purchase rate. Referenced by all stock structures. |
| `Warehouse` | A stock location | `apps/inventory/models.py:61-98` | Separates balances and FIFO queues by location. |
| `Bin` | Current `(item, warehouse)` snapshot | `apps/inventory/models.py:189-231` | Stores current actual quantity, reservations, valuation rate, and stock value. One row per item/warehouse. |
| `StockLedgerEntry` | One immutable-in-intent movement row | `apps/inventory/models.py:234-403` | Stores signed movement, running quantity, rates, value, and the resulting FIFO queue. Its class method is the core mutation primitive. |
| `StockEntry` / `StockEntryDetail` | Manual material receipt or Store-to-unit transfer document | `apps/inventory/models.py:406-524` | Draft document. `apps/inventory/services.py:16-148` posts it to SLEs. |
| `PurchaseReceipt` / `PurchaseReceiptItem` | Supplier receipt document | `apps/inventory/models.py:609-724` | Draft document. `submit_purchase_receipt()` posts positive SLEs into the configured central Store. |
| `StockReconciliation` / items | Physical-count or explicit consumption adjustment | `apps/inventory/models.py:525-608` | `submit_stock_reconciliation()` posts the difference between counted quantity and Bin quantity. |
| `Order` / `OrderItem` | POS sale or return document | `apps/orders/models.py:93-486` | Drink sales create negative SLEs at settlement. Food sales do not deduct inventory. Returns create positive SLEs. |
| Inventory services | Posting and reversal workflows | `apps/inventory/services.py:16-402` | Lock documents/Bins, validate, call SLE posting, and transition status. |
| Order services | POS reservation, sale, cancellation, and return flow | `apps/orders/services.py:153-297`, `1009-1191` | Reserves drink stock in draft, deducts it at settlement, and restores it on cancellation/return. |
| Inventory views/forms | HTTP and form entry points | `apps/inventory/views.py:355-681`, `apps/inventory/forms.py:88-193` | Create draft documents and call services on submit/cancel. |
| Reports | Read-side consumers of SLEs/Bins | `apps/reports/sources.py:57-165` | Uses SLE outgoing/incoming rates for drink COGS and kitchen consumption. |

There are no inventory signals, repositories, background jobs, or event handlers. The only discovered Django signals are user-account signals in `apps/users/signals.py`.

### 1.2 Sources of truth

- **Source transaction truth:** the submitted `PurchaseReceipt`, `StockEntry`, `StockReconciliation`, or `Order` explains why movement occurred.
- **Movement/audit truth:** non-cancelled plus cancelled `StockLedgerEntry` rows are the movement history. Original SLEs remain and are marked `is_cancelled=True`; reversal SLEs are added.
- **Current quantity read truth:** `Bin.actual_qty` is the fast current balance used by POS availability, reservations, reconciliation, and most inventory pages.
- **Current valuation read truth:** `Bin.valuation_rate` and `Bin.stock_value` mirror the latest posting for that item/warehouse.
- **FIFO truth:** the queue on the latest non-cancelled SLE for the item/warehouse. `Bin.current_stock_queue()` explicitly loads that queue from the latest SLE (`models.py:217-231`).
- **Last purchase rate:** `Item.last_purchase_rate`, updated by purchase receipts and material receipts, is informational and is not the FIFO queue.

The ledger is intended to be the reconstructable movement history, but the implementation does not provide a rebuild command and does not recalculate later SLEs when an old transaction is inserted or changed.

## 2. The central posting primitive

### Behavior: create one stock movement

**Implemented in:** `apps/inventory/models.py:269-403`

**Entry point:** `StockLedgerEntry.create_entry(...)`

Call chain:

```text
StockLedgerEntry.create_entry()
    -> transaction.atomic()
    -> Bin.get_or_create_bin()
    -> SELECT FOR UPDATE Bin
    -> StockLedgerEntry._create_entry_locked()
        -> load latest non-cancelled SLE queue
        -> update queue and calculate rates/value
        -> create SLE
        -> update Bin
```

`_create_entry_locked()` is also called directly by the inventory and order services after those services have already locked the relevant Bins.

The method:

1. Reads `bin_obj.actual_qty` and `bin_obj.valuation_rate`.
2. Computes `new_qty = current_qty + actual_qty` (`models.py:316-320`).
3. Rejects a negative result only when `prevent_negative=True`.
4. Loads the queue from the latest non-cancelled SLE ordered by `posting_datetime DESC, pk DESC` (`models.py:326-339`).
5. For positive quantity, appends `[actual_qty, rate]` (`342-344`).
6. For negative quantity, consumes queue entries from index zero (`345-367`).
7. Calculates `stock_value = new_qty * valuation_rate` (`371`).
8. Creates the SLE containing both the movement and the resulting queue (`373-386`).
9. Mirrors the resulting quantity/rate/value into the Bin (`388-401`).

The code does not make an incoming SLE's queue layer point back to a receipt row. FIFO provenance is therefore represented implicitly by queue order and rates, not by a foreign key to the source receipt.

## 3. Stock addition flows

### 3.1 Purchase Receipt

Chronological path:

```text
POST /backoffice/inventory/purchase-receipts/<pk>/submit/
    -> inventory.views.purchase_receipt_submit()
    -> inventory.services.submit_purchase_receipt(receipt)
    -> lock PurchaseReceipt
    -> validate lines and configured Store
    -> lock/create Store Bins
    -> StockLedgerEntry._create_entry_locked(+received_qty, rate=line.rate)
        -> create positive Purchase Receipt SLE
        -> update Store Bin
    -> update Item.last_purchase_rate
    -> set receipt.warehouse, total, status=SUBMITTED
```

The view is `apps/inventory/views.py:660-681`. The service is `apps/inventory/services.py:272-324`.

Important database effects per line:

- `StockLedgerEntry`: one row, `voucher_type="Purchase Receipt"`, `voucher_no=str(receipt.pk)`, `voucher_detail_no=str(line.pk)`, positive `actual_qty`, `incoming_rate=line.rate`.
- `Bin`: Store `actual_qty`, valuation rate, and stock value are updated.
- `PurchaseReceipt`: assigned configured Store, totalled, submitted.
- `Item.last_purchase_rate`: bulk-updated to the line rate.

The form sets the receipt warehouse to the configured Store before saving (`apps/inventory/forms.py:151-159`), and the service validates it again. A receipt never posts to an arbitrary warehouse.

### 3.2 Material Receipt Stock Entry

Chronological path:

```text
POST /backoffice/inventory/stock-entries/<pk>/submit/
    -> inventory.views.stock_entry_submit() [views.py:430-439]
    -> inventory.services.submit_stock_entry(entry)
    -> lock StockEntry and validate central Store/configuration
    -> lock relevant Store Bins
    -> for each detail:
       set source=None, target=Store
       _create_entry_locked(+detail.qty, rate=detail.basic_rate)
       update Item.last_purchase_rate
    -> save detail warehouse fields
    -> mark StockEntry SUBMITTED
```

The service implementation is `apps/inventory/services.py:16-148`, with receipt behavior at `96-113`. It is structurally similar to a purchase receipt but the source document is `StockEntry` and the voucher type is `Stock Entry`.

### 3.3 Material Transfer

The implementation supports only Store-to-production-unit transfer. It does not expose a general-purpose Material Issue purpose: `StockEntry.purpose` choices are only `MATERIAL_RECEIPT` and `MATERIAL_TRANSFER` (`apps/inventory/models.py:409-415`; confirmed by `test_stock_entry.py:50-52`).

Validation in `submit_stock_entry()` (`services.py:30-61`) resolves:

- FOOD -> configured FOOD `ProductionUnit.warehouse` (Kitchen).
- DRINKS -> `Restaurant.default_warehouse` (Bar/POS), which must also be the DRINKS production unit warehouse.
- Store, Kitchen, and Bar must be distinct.

For each line, `services.py:114-141` performs two SLE mutations:

```text
Store:  -qty, rate=0, prevent_negative=True
    -> FIFO consumes Store's oldest layers
    -> outgoing.outgoing_rate is the weighted FIFO cost

Target: +qty, rate=outgoing.outgoing_rate
    -> creates a new target FIFO layer at the transferred cost
```

Thus the transfer creates **two SLEs per detail**, one negative at the source and one positive at the target. The original receipt layer is not moved by identity. It is consumed in the source queue and recreated as a target layer using the weighted outgoing rate. For a transfer of 3 units from layers `2 @ 100` and `3 @ 200`, the target rate is `(2*100 + 1*200)/3 = 133.33`, as tested in `apps/inventory/tests/test_stock_entry.py:76-95`.

The two SLEs are inside the service's `@transaction.atomic` boundary (`services.py:15`), so a failure rolls back both sides and the Bin updates.

### 3.4 Stock Reconciliation and other increases

`submit_stock_reconciliation()` (`services.py:173-247`) is the other supported stock increase path. For each line:

```text
current_qty = locked Bin.actual_qty
difference = counted_qty - current_qty
if difference > 0:
    _create_entry_locked(+difference, voucher_type="Stock Reconciliation")
```

Opening stock uses `line.valuation_rate` as the incoming rate. A normal reconciliation passes rate zero (`services.py:229-243`), so it appends a zero-rate layer. A positive physical-count correction is therefore not necessarily valued at a meaningful purchase cost.

POS returns are another increase path and are covered below. Food POS sales are explicitly not an increase or deduction path: food consumption must be posted through a `CONSUMPTION` reconciliation at Kitchen (`docs/workflows/inventory.md:30`, `services.py:196-203`).

## 4. Stock Ledger Entries

### 4.1 Fields

`StockLedgerEntry` is defined at `apps/inventory/models.py:234-263`.

| Field | Meaning |
|---|---|
| `item`, `warehouse` | The item/location pair affected. Both use `PROTECT`. |
| `posting_datetime` | `auto_now_add=True`; actual database creation time, not document `posting_date`. |
| `voucher_type`, `voucher_no`, `voucher_detail_no` | Loose source-document identity. `voucher_no` is normally the parent PK as a string; detail number is line PK. |
| `actual_qty` | Signed movement: positive receipt, negative issue, zero adjustment. |
| `qty_after_transaction` | `Bin.actual_qty + actual_qty` at posting time. |
| `incoming_rate` | Input rate for positive movement; zero for ordinary issues. |
| `outgoing_rate` | FIFO weighted cost of a negative movement. |
| `valuation_rate` | Weighted average rate of the queue remaining after the movement. For positive movement, it is set to the incoming rate, not a cumulative weighted average. |
| `stock_value` | `new_qty * valuation_rate`. |
| `stock_queue` | JSON list of remaining `[quantity, rate]` layers after this movement. |
| `is_cancelled` | Marks the original row cancelled after a reversal is posted. |

Fields are `editable=False` for calculated values, but that is a form/admin presentation restriction, not a database immutability mechanism. There is no overridden `StockLedgerEntry.save()` or `delete()` guard.

### 4.2 Ordering and historical behavior

The queue source is selected by:

```python
StockLedgerEntry.objects.filter(
    item=item, warehouse=warehouse, is_cancelled=False
).order_by("-posting_datetime", "-pk").first()
```

Because `posting_datetime` is creation time, the order is write order. `StockEntry.posting_date`, `PurchaseReceipt.posting_date`, and reconciliation `posting_date` do not control SLE ordering. There is no reposting or recalculation service when an old-dated transaction is inserted.

Each SLE stores a snapshot of the queue after its own movement. Older SLE snapshots are historical; the latest non-cancelled SLE is the operational queue source. `qty_after_transaction` is also a historical running value calculated from the Bin at the time, not dynamically recomputed from all ledger rows.

### 4.3 Cancellation/reversal

Inventory document cancellation uses `_reverse_voucher()` (`services.py:350-379`):

1. Lock non-cancelled original SLEs for the voucher.
2. Lock involved Bins in item/warehouse order.
3. For each original SLE, create an inverse movement with `actual_qty=-sle.actual_qty`.
4. If the original was negative, pass its `outgoing_rate` as the reversal incoming rate; if original was positive, pass zero.
5. Mark the original SLE `is_cancelled=True`.

The original SLE is not deleted. The inverse row has voucher type such as `Purchase Receipt Cancellation` or `Stock Entry Cancellation`. `prevent_negative=sle.actual_qty > 0` prevents cancelling an incoming movement if current stock is insufficient.

The inverse is applied to the **current** queue, not the original historical queue. That is deliberate in the code and is demonstrated by `test_purchase_receipt.py:106-121` and `test_stock_entry.py:139-157`, but it means cancellation after later movements can produce a different current-layer result than removing the original event chronologically.

## 5. FIFO and the stock queue

### 5.1 What the queue is

The queue is a JSON text field on SLE, not a model:

```text
[["quantity", "rate"], ["quantity", "rate"], ...]
```

Each pair is a remaining cost layer. A positive movement appends a layer. A negative movement consumes from the front. Every new SLE stores the resulting queue, so the queue is both:

- the persisted operational FIFO state;
- a valuation mechanism for outgoing cost;
- a derived snapshot of prior SLE processing.

It is not an independent cache because FIFO reads it directly to determine the next deduction. It is not a source transaction because it contains no receipt FK or transaction identity.

### 5.2 Numerical example

Assume one item in Store:

| Event | SLE actual qty | Queue after event | Bin qty | Outgoing rate | Bin valuation |
|---|---:|---|---:|---:|---:|
| Receipt A, 10 @ 100 | +10 | `[(10,100)]` | 10 | 0 | 100 |
| Receipt B, 15 @ 120 | +15 | `[(10,100),(15,120)]` | 25 | 0 | 120 |
| Receipt C, 20 @ 130 | +20 | `[(10,100),(15,120),(20,130)]` | 45 | 0 | 130 |
| Sale/issue 18 | -18 | `[(7,120),(20,130)]` | 27 | `(10*100+8*120)/18 = 108.888...` | `(7*120+20*130)/27 = 127.407...` |

The code does not round the intermediate FIFO division explicitly. The DecimalField database precision may quantize persisted values. The remaining layer state is:

- Receipt A: fully consumed, 0 left.
- Receipt B: 8 consumed, 7 left.
- Receipt C: untouched, 20 left.

The SLE does not store a per-receipt consumption allocation. It stores only the aggregate `outgoing_rate` and resulting queue. The UI does not expose receipt-layer allocation; inventory pages expose SLEs and Bin balances. The queue can be viewed indirectly through `Bin.current_stock_queue()` or directly from SLE data, but no dedicated queue UI was found.

### 5.3 Edge behavior

- If a layer is insufficient, it is fully popped and the loop continues.
- If partially sufficient, its quantity is reduced in place.
- If the queue is empty and a negative movement is allowed (`prevent_negative=False`), the quantity can become negative while `outgoing_rate` is zero. Reconciliation and some direct calls allow this; transfers and drink sales use `prevent_negative=True`.
- A return adds a new layer. It does not restore the original receipt layer identity.
- A cancellation adds an inverse movement against the current queue and then cancels the source row.
- Historical insertion/change is unsupported: there is no replay/repost operation.

## 6. Bin stock

`Bin` is defined at `apps/inventory/models.py:189-200` and is unique on `(item, warehouse)`.

- `actual_qty`: current physical ledger quantity.
- `reserved_qty`: draft drink-order reservation only; it does not change actual stock.
- `valuation_rate`: latest posting's remaining-queue weighted rate.
- `stock_value`: latest posting's `new_qty * valuation_rate`.

Creation occurs via `get_or_create_bin()` or `get_or_create_bin_id()`. Updates occur only as part of posting through `_create_entry_locked()` (`models.py:388-401`), except direct reservation updates in `orders.services.reserve_drink_stock()` (`services.py:701-746`) and migration/test/direct ORM operations.

Example:

```text
Initial: no Bin
Receipt +10 @100 -> Bin actual=10, valuation=100, value=1000
Issue -4         -> Bin actual=6, valuation=100, value=600
Issue -6         -> Bin actual=0, valuation=0, value=0
```

Bins are not rebuilt from SLE anywhere in the repository. If a Bin is inconsistent, normal reads and availability use the Bin; FIFO uses the latest SLE queue. There is no repair command that reconciles the two. This makes a damaged Bin operationally significant even though the ledger contains movement history.

## 7. Sales and deduction

### 7.1 Draft sale: reservation only

`add_order_line()` (`apps/orders/services.py:376-414`) reserves only DRINKS. `reserve_drink_stock()` locks the drink Bin, checks `actual_qty - reserved_qty + owned`, and increments `reserved_qty`. The POS availability builder (`services.py:754-787`) displays unreserved drink quantity. No SLE is created while the order is draft.

### 7.2 Settlement: drink deduction

The relevant chain is:

```text
POS payment POST
    -> orders.views settlement endpoint
    -> orders.services.settle_order()
    -> _snapshot_stock_warehouse()
    -> _validate_drink_stock_for_settlement()
    -> create payment rows and submit Order
    -> _convert_drink_reservations()
    -> StockLedgerEntry._create_entry_locked(-OrderItem.qty)
```

The settlement path is `apps/orders/services.py:153-243`. ` _convert_drink_reservations()` is `1073-1100`.

It locks/rechecks drink Bins, subtracts this order's owned reservation, and creates one negative `POS Order` SLE per drink line. FIFO chooses layers from the latest queue in that warehouse. Food lines do not enter this function and therefore do not deduct stock at POS settlement.

### 7.3 Order cancellation and returns

For a submitted unpaid order, `cancel_order()` calls `_restore_stock()` (`orders/services.py:246-297`, `1166-1191`). It creates positive `POS Order Cancellation` SLEs for restockable drink lines. A submitted paid order cannot be cancelled; it must use refund/return flow.

`submit_return()` calls `_restore_stock(..., voucher_type="POS Return")` (`orders/services.py:533-573`). Return lines are negative quantities in the return document, but restoration posts positive inventory. `not_restockable` lines skip the SLE and are treated as wastage by P&L (`apps/reports/sources.py:109-147`).

The positive restore uses `StockLedgerEntry.create_entry()` without an explicit rate (`orders/services.py:1184-1191`), so the new FIFO layer has rate zero. This is a material valuation behavior: the code restores quantity but does not preserve the original sale's outgoing cost as the incoming layer rate.

## 8. Comparison

| Component | Purpose | Source of truth? | Stores quantity? | Stores valuation? | Used for FIFO? | Updated when? |
|---|---|---:|---:|---:|---:|---|
| Source document | Business explanation and lifecycle | Yes for transaction identity | Requested line qty | Purchase/sale rates | No directly | Draft/edit/submit/cancel |
| SLE | Append-only movement/audit row | Yes for movement history | Signed actual and running qty | Incoming, outgoing, valuation, stock value | Yes, via queue snapshot | Every posted movement |
| SLE `stock_queue` | Remaining FIFO layers after one movement | Operational FIFO state | Layer quantities | Layer rates | Yes | Every SLE posting |
| Bin | Fast current item/warehouse state | Yes for current reads | Actual and reserved qty | Valuation rate and stock value | Indirectly; latest queue is read separately | Every SLE; reservations update reserved only |
| FIFO algorithm | Cost allocation policy | No persisted object | Consumes layer quantities | Computes outgoing/remaining valuation | N/A | Inside `_create_entry_locked()` |
| `Item.last_purchase_rate` | Last buy-rate convenience field | No | No | Last receipt rate only | No | Purchase/material receipt submit/cancel |

The structures exist because replaying every historical SLE for every POS availability read would be expensive, while source documents alone do not encode inter-warehouse cost movement or exact post-transaction queue state. The tradeoff is denormalized state: Bin and queue must remain synchronized.

## 9. Purchase Receipt lifecycle cases

### Creation and submission

Creation only creates `PurchaseReceipt` and `PurchaseReceiptItem` rows (`views.py:603-613`). No stock changes occur until the submit POST (`views.py:660-669`). Submission creates positive SLEs and updates Bins as described above.

### Cancellation

`cancel_purchase_receipt()` (`inventory/services.py:326-342`) reverses all non-cancelled receipt SLEs, marks them cancelled, reverts `Item.last_purchase_rate` to the latest other submitted purchase receipt by posting date/PK, and marks the receipt cancelled.

If the received quantity has been consumed, the positive reversal uses `prevent_negative=True` and raises `ValidationError`. The whole atomic operation rolls back, including earlier line reversals; this is tested in `test_purchase_receipt.py:76-104`.

If later stock exists, cancellation uses the current FIFO queue. The test at `test_purchase_receipt.py:106-121` shows a receipt `2 @100`, later receipt `2 @200`, then cancellation: the cancellation consumes the current `100` layer if it is still present, leaving Bin `2 @200`. This is current-queue reversal, not historical event removal.

### Amendment and later transactions

Submitted receipts cannot be edited. `PurchaseReceipt.save()` allows only transition to `CANCELLED`; item `save()`/`delete()` calls `_assert_document_is_draft()` (`models.py:653-711`). There is no amend-and-repost method. A later receipt is simply appended according to actual insertion time, regardless of its `posting_date`.

## 10. Stock Entry lifecycle cases

### Material receipt

One detail produces one positive SLE into Store. `basic_rate` becomes the incoming FIFO rate and `Item.last_purchase_rate`.

### Transfer

One detail produces:

```text
Store Bin:   -qty, FIFO cost computed from source queue
Target Bin:  +qty, incoming rate = source outgoing FIFO rate
```

The source quantity cannot go below zero because `prevent_negative=True`. Since both movements are atomic, a failed target posting rolls back source deduction. The original receipt layer is not preserved as an identity; the target gets a new aggregate-rate layer.

### Material issue

There is no document type or service path for it. Issues can still be produced by direct `StockLedgerEntry.create_entry()` calls, POS drink settlement, and negative reconciliation differences. This distinction matters when tracing data: not every negative SLE has a Stock Entry source.

## 11. Cancellation example

For:

```text
Purchase Receipt: +100 @100
Sale/issue:       -30
Cancel receipt:   +100 inverse movement
```

The SLE history is conceptually:

| Row | Voucher | Actual qty | State |
|---|---|---:|---|
| 1 | Purchase Receipt | +100 | `is_cancelled=True` after cancellation |
| 2 | Issue/POS Order | -30 | active |
| 3 | Purchase Receipt Cancellation | -100 | attempted inverse of row 1 |

The cancellation does **not** post `+100` in this implementation. `_reverse_voucher()` uses `actual_qty=-sle.actual_qty`, so reversing the original positive receipt attempts to deduct 100. Current quantity is 70, so `prevent_negative=True` rejects it and the entire cancellation rolls back. The receipt remains SUBMITTED and row 1 remains active. This is intentional protection against removing stock that has already been consumed, not a partial reversal.

If the original 100 is still entirely available, the inverse is `-100`, current Bin becomes zero, and the original row is marked cancelled. The wording “cancel receipt: +?” must therefore be read as “create the inverse of the original movement”; for an incoming receipt, the inventory reversal is negative.

For a positive transfer-in SLE, cancellation similarly creates a negative target reversal. For the negative source SLE, it creates a positive source reversal, passing the original outgoing rate as its incoming rate (`services.py:366-375`).

## 12. Complete lifecycle example

Assume Store, Kitchen, and Bar are distinct, and the item is FOOD. Ignore food POS sales because they do not deduct stock.

| Stage | Store SLE effect | Kitchen SLE effect | Store Bin | Kitchen Bin | Relevant FIFO |
|---|---|---|---:|---:|---|
| Receive 100 @100 | `+100`, queue `[(100,100)]` | none | 100 @100 | 0 | Store has 100 @100 |
| Transfer 40 | `-40`, outgoing 100, queue `[(60,100)]` | `+40 @100`, queue `[(40,100)]` | 60 @100 | 40 @100 | Cost follows transfer |
| Consume 20 Store | `-20`, queue `[(40,100)]` | none | 40 @100 | 40 @100 | Direct issue/reconciliation path required |
| Consume 10 Kitchen | none | `-10`, queue `[(30,100)]` | 40 @100 | 30 @100 | Kitchen FIFO consumes its own layer |
| Receive another 50 @130 | `+50`, queue `[(40,100),(50,130)]` | none | 90 @130 valuation field | 30 @100 | Queue retains both layers |
| Issue 80 Store | `-80`; consumes 40 @100 + 40 @130; remaining `[(10,130)]` | none | 10 @130 | 30 @100 | outgoing `(4000+5200)/80=115` |
| Cancel second receipt | Attempts `-50` against current Store queue | none | would require current qty >=50; current is 10 | unchanged | Fails with insufficient stock and rolls back |

The `Bin.valuation_rate` after the 50-unit receipt is set to 130 by the positive-posting rule, even though the queue contains 40 units at 100 and 50 at 130. After the 80-unit issue, remaining valuation becomes 130 because only the second layer remains. The queue, not a receipt relation, records the surviving layers.

## 13. Hidden behavior and transaction boundaries

- Inventory services are decorated with `@transaction.atomic`; order settlement, cancellation, and returns are also atomic.
- Inventory posting locks the document and Bins. Multi-line Bin locks are ordered by item/warehouse to reduce deadlocks (`inventory/services.py:69-90`).
- `StockLedgerEntry.create_entry()` itself locks a Bin, but direct callers that use `_create_entry_locked()` must already hold the correct lock.
- Drink draft reservations update `Bin.reserved_qty` without SLEs. Deleting a draft order releases those reservations through `Order.delete()` (`orders/models.py:252-271`).
- `editable=False` does not prevent direct ORM `update()` or direct low-level SLE calls. `docs/database/transactions.md:46-48` explicitly identifies these bypasses.
- No signal updates inventory.
- No background job updates inventory.
- POS availability reads `Bin.actual_qty - Bin.reserved_qty`, not SLE aggregation.
- Reports read SLEs, particularly `outgoing_rate` for sales and consumption and `incoming_rate` for returns (`reports/sources.py:85-165`).

## 14. Risks and inconsistencies

### High: SLE has no actual model-level immutability

`StockLedgerEntry` docstring says it is immutable, but there is no `save()`/`delete()` guard. Calculated fields are only `editable=False`. Admin, direct ORM, or application code can change/delete rows, breaking Bin and queue synchronization.

### High: No historical repost/rebuild

SLE ordering uses `auto_now_add` creation time, not document posting date. Inserting a transaction with an earlier `posting_date` later still appends it to the current queue. There is no replay of subsequent SLEs, Bin rebuild, or FIFO correction.

### High: Cancellation is current-state reversal, not chronological reversal

`_reverse_voucher()` applies inverse quantities to the current queue. It can fail after stock has moved, or consume a different layer from the one originally created. It also makes cancellation valuation depend on movements that happened after the source transaction.

### High: Return/cancellation restoration can create zero-rate layers

`orders.services._restore_stock()` calls `StockLedgerEntry.create_entry()` without a rate. Restored quantity therefore appends a zero-rate FIFO layer. The source sale's outgoing cost is not passed into the return SLE.

### Medium: Negative stock is possible on some paths

`prevent_negative` is opt-in. POS drink sales and transfers enable it, but direct SLE calls and reconciliation posting pass `False`. A negative Bin can therefore exist through permitted low-level/reconciliation paths.

### Medium: Positive receipt valuation rate is not a weighted current rate

On every positive movement, `valuation_rate = rate`, while the queue may contain multiple rates. `stock_value` is therefore based on the latest incoming rate for the whole remaining quantity until a negative movement recalculates the queue weighted average.

### Medium: Reconciliation rate zero can create zero-cost layers

Normal reconciliation differences pass rate zero. A positive correction thus enters FIFO at zero unless it is opening stock with an explicit rate.

### Medium: Cancellation order is not explicitly deterministic

`_reverse_voucher()` converts the filtered SLE queryset to a list without an explicit ordering. A transfer has source and target rows, and reversal order can affect intermediate queue state. Atomicity protects all-or-nothing behavior, but not necessarily deterministic intermediate valuation.

### Low: `Bin.current_stock_queue()` returns empty for malformed JSON

It catches `JSONDecodeError` and `TypeError` and returns `[]` (`models.py:225-230`). That silently treats corrupt FIFO data as an empty queue while Bin quantity may remain nonzero.

## 15. Final mental model

1. **Where does stock physically enter?** Through a submitted Purchase Receipt, Material Receipt Stock Entry, Opening Stock reconciliation, or positive reconciliation adjustment.
2. **What represents the event?** The source document plus one positive SLE per item/warehouse movement.
3. **What creates the SLE?** The inventory service or order service calls `StockLedgerEntry._create_entry_locked()` or `create_entry()`.
4. **What updates Bin?** `_create_entry_locked()` writes actual quantity, valuation rate, and stock value; reservation code writes reserved quantity.
5. **What creates the FIFO layer?** A positive SLE appends `[qty, rate]` to its JSON `stock_queue`.
6. **What finds stock on sale?** The latest non-cancelled SLE queue for that item/warehouse.
7. **How does FIFO choose?** It consumes queue index zero, then subsequent layers until the requested quantity is satisfied.
8. **Where is remaining quantity stored?** In the latest SLE's serialized queue and in `Bin.actual_qty`; the Bin does not store layer detail.
9. **How does transfer work?** Negative source SLE consumes source FIFO; positive target SLE creates a new layer at the source's weighted outgoing rate.
10. **How do cancellation/reversal work?** Original SLEs remain but are marked cancelled; inverse SLEs are posted against current state. The operation is atomic and refuses incoming cancellation when current quantity is insufficient.
11. **Which structure wins if they disagree?** Current operational reads use Bin; FIFO uses the latest non-cancelled SLE queue; there is no automatic reconciliation between them.
12. **Can current inventory be reconstructed from the ledger?** In principle, movement quantities can be summed, and FIFO can be replayed in creation order. In practice, the repository has no rebuild implementation, and historical insertions, direct SLE mutation, malformed queues, or differing cancellation order can make Bin/queue state diverge from a clean replay.

# Daily Profit and Loss: Code-Level Walkthrough

This document explains the implemented Daily P&L in RestPOS. It follows the actual code in:

- `apps/reports/models.py`
- `apps/reports/pnl_models.py`
- `apps/reports/sources.py`
- `apps/reports/services.py`
- `apps/reports/forms.py`
- `apps/reports/views.py`
- `apps/reports/urls.py`
- `apps/reports/tests/`
- the order, inventory, and staff services that provide source data

The central fact is:

> Daily P&L is a manager-created, submitted snapshot calculated from live operational data. It does not post accounting GL entries.

The report does not calculate profit by reading the accounting journal. It reads submitted orders, inventory SLEs, kitchen-consumption reconciliations, shift closings, P&L configuration, recurring expense templates, and draft-specific inputs.

## 1. Mental Model First

```text
Manager creates DailyPnL draft
        ↓
Draft inputs are saved
  electricity readings
  employee override
  material quantities
  ad-hoc expenses
        ↓
Preview or submit calls compute_daily_pnl()
        ↓
Live sources are queried
  submitted orders
  drink POS SLEs
  POS return SLEs
  kitchen consumption SLEs
  submitted shift closings
  P&L configuration/templates
        ↓
LineSpec rows and totals are calculated
        ↓
On submit, rows and totals are persisted
        ↓
DailyPnL becomes SUBMITTED and immutable
```

There are two different kinds of data:

- **Live inputs:** orders, SLEs, closings, and configuration are queried when preview or submit runs.
- **Snapshot outputs:** totals, statement lines, COGS detail, and consumption detail are written when submit runs.

Consequently, a draft can change as operational data changes. A submitted P&L does not change when settings or source transactions later change, because its calculated fields and child rows are stored.

## 2. Architecture

### 2.1 Models and responsibilities

| Component | Represents | Important implementation | Relationship to P&L |
|---|---|---|---|
| `PnLConfiguration` | Singleton report settings | `apps/reports/models.py:18-67` | Business-day start hour, electricity rate, daily depreciation, cash-variance toggle. |
| `PnLMaterial` | Catalogued consumable used as a manual P&L input | `apps/reports/models.py:70-91` | Draft quantity is multiplied by the current catalog rate during computation; rate/amount are snapshotted on submit. |
| `PnLRecurringExpense` | Reusable expense template | `apps/reports/models.py:94-138` | Defines direct, indirect, employee, daily, monthly, or percentage expenses. |
| `DailyPnL` | One report document for one business date | `apps/reports/pnl_models.py:24-194` | Owns status, period, input values, persisted totals, and amendment link. |
| `DailyPnLMaterialQty` | Draft quantity of a `PnLMaterial` | `pnl_models.py:197-220` | Input only while draft; rate and amount are filled during submission. |
| `DailyPnLAdHoc` | One-off expense | `pnl_models.py:223-248` | Draft input classified as DIRECT or INDIRECT and optionally FOOD/DRINKS. |
| `DailyPnLLine` | Persisted statement row | `pnl_models.py:251-310` | Immutable-on-submit breakdown with section, department amounts, percentage, source, memo flag, and order. |
| `DailyPnLCogsRow` | Persisted drink COGS/return/wastage detail | `pnl_models.py:312-330` | Written on submit from drink SLEs and return lines. |
| `DailyPnLConsumptionRow` | Persisted kitchen-consumption detail | `pnl_models.py:332-342` | Written on submit from FOOD consumption reconciliation SLEs. |
| `Order`/`OrderItem` | POS sales and returns | `apps/orders/models.py` | Submitted orders provide revenue. Their drink settlement creates source SLEs for COGS. |
| `StockLedgerEntry` | Inventory movement | `apps/inventory/models.py` | Drink SLE `outgoing_rate` supplies sale COGS; return SLE `incoming_rate` reduces COGS. |
| `StockReconciliation` | Physical/consumption adjustment | `apps/inventory/models.py` | FOOD `CONSUMPTION` SLEs supply the kitchen-consumption memo. |
| `POSClosingEntry` | Shift close | `apps/staff/models.py` | `total_short_excess` supplies optional cash variance. |

### 2.2 Services and sources

`apps/reports/services.py` contains the report engine:

- `business_day_window()` is imported from `sources.py` and defines the report period.
- `compute_daily_pnl()` builds a non-persisted `Computation` object.
- `submit_daily_pnl()` recomputes, writes the snapshot, and submits the document.

`apps/reports/sources.py` contains source queries and small calculations:

- `orders_in_window()`
- `sales_by_department()`
- `round_off()`
- `drink_cogs()`
- `kitchen_consumption()`
- `cash_variance()`
- `electricity()`
- `recurring_amount()`

The views are orchestration only. They validate manager access, save draft inputs, call the service, and render pages. They do not calculate P&L themselves.

There are no P&L signals, repositories, background jobs, or GL event handlers. `submit_daily_pnl()` explicitly documents “no GL posting” and the test `apps/reports/tests/test_compute.py:204-213` verifies that submitting a report does not increase `GLEntry` count.

## 3. Business-Day Period

### Implementation

**File:** `apps/reports/sources.py:21-25`

```python
def business_day_window(business_date, start_hour):
    start = timezone.make_aware(
        datetime.combine(business_date, datetime.min.time().replace(hour=start_hour)),
        tz,
    )
    return start, start + timedelta(days=1)
```

For business date `D` and configured start hour `H`, the window is:

```text
[D at H:00, next calendar date at H:00)
```

Example with start hour 06:00:

```text
Business date: 2026-08-19
Included:      2026-08-19 06:00 through 2026-08-20 05:59:59...
```

`DailyPnL._refresh_period()` (`pnl_models.py:110-114`) stores the current window on draft creation/save. `compute_daily_pnl()` recalculates the window from the current configuration (`services.py:79-83`). On submission, the final period is stored again using the current configuration (`services.py:297-299`).

### Revenue uses order posting fields

`orders_in_window()` (`sources.py:36-40`) first filters submitted orders by a small set of calendar dates, then converts each order's `posting_date` and `posting_time` using `order_datetime()` and applies the actual datetime window.

Only `Order.status=SUBMITTED` rows are included. Draft, cancelled, and discarded orders are excluded.

Returns are submitted orders too. Their negative `OrderItem.qty`/amount therefore affects sales totals as a negative revenue amount.

The test `apps/reports/tests/test_compute.py:32-50` verifies that an order at 01:00 belongs to the previous business date when the day starts at 06:00.

## 4. Creating and Editing a Draft

### Create path

```text
POST reports:daily_pnl_create
    -> views.daily_pnl_create()
    -> _require_manager()
    -> DailyPnLForm.save()
    -> DailyPnL.save()
        -> _refresh_period()
        -> full_clean()
        -> INSERT DailyPnL
    -> _seed_material_rows()
        -> create one qty=0 row for each enabled PnLMaterial
    -> redirect to update page
```

Implementation: `apps/reports/views.py:90-99`.

The form accepts:

- `business_date`
- optional electricity opening/closing readings
- optional employee cost override
- remarks

The form disables `business_date` when editing an existing document (`apps/reports/forms.py:39-58`). The model also rejects a business-date change after creation (`pnl_models.py:132-144`).

### Draft input persistence

The update view (`views.py:114-141`) saves the parent form and both inline formsets in one `transaction.atomic()` block:

- `DailyPnL`
- `DailyPnLMaterialQty`
- `DailyPnLAdHoc`

Material rows accept quantity only. Their `rate` and `amount` are not editable and remain zero until submission. The computation reads `row.material.rate`, not the stored row rate (`services.py:114-122`).

Ad-hoc rows contain label, amount, DIRECT/INDIRECT section, and optional department. They require amount greater than zero (`pnl_models.py:239-248`).

## 5. Computation Entry Point

### Behavior: calculate a P&L without persisting it

**Implemented in:** `apps/reports/services.py:79-253`

Call chain:

```text
compute_daily_pnl(pnl)
    -> PnLConfiguration.load()
    -> business_day_window()
    -> orders_in_window()
    -> sales_by_department()
    -> round_off()
    -> drink_cogs()
    -> kitchen_consumption()
    -> electricity()
    -> material quantities
    -> recurring expense templates
    -> ad-hoc rows
    -> calculate gross profit, prime cost, net profit
    -> return Computation(totals, lines, cogs_rows, consumption_rows)
```

`Computation` and `LineSpec` are dataclasses (`services.py:53-72`). At preview time they are in memory only. At submit time they become database rows.

## 6. Revenue Calculation

### Sales by department

`sales_by_department()` (`sources.py:43-50`) queries `OrderItem.amount` for the selected submitted order IDs and groups by the item line's stored `department` snapshot.

```text
food sales   = SUM(OrderItem.amount where department=FOOD)
drink sales  = SUM(OrderItem.amount where department=DRINKS)
gross sales  = food sales + drink sales
```

`OrderItem.amount` is generated from quantity and selling rate in `apps/orders/models.py:454-484`. A return line has negative quantity, so its amount is negative and reduces department revenue.

The computation quantizes gross sales to two decimal places:

```python
gross = (food + drinks).quantize(TWO)
```

### Round-off and net sales

Each order stores:

- `grand_total`
- `rounded_total`
- `rounding_adjustment`

`round_off()` sums `Order.rounding_adjustment` over the selected orders (`sources.py:53-55`). Then:

```text
net sales = gross sales + total order rounding adjustment
```

The P&L displays round-off as its own line, but the amount is not split between FOOD and DRINKS (`services.py:92-94`).

## 7. Drink COGS

### What counts as COGS

The current implementation calculates ordinary COGS only for DRINKS. Food sales have zero COGS in this report. FOOD inventory consumption is separately reported as a memo line and does not reduce gross profit.

This is tested in `apps/reports/tests/test_compute.py:74-79` and `97-130`.

### Sale COGS source

`drink_cogs()` (`sources.py:85-108`) queries active SLEs with:

```text
is_cancelled=False
posting_datetime inside [start, end)
voucher_type="POS Order"
actual_qty < 0
item.department=DRINKS
```

For each row:

```text
quantity = abs(SLE.actual_qty)
rate     = SLE.outgoing_rate
amount   = quantity * outgoing_rate
```

The `outgoing_rate` was produced by inventory FIFO in `StockLedgerEntry._create_entry_locked()` when settlement deducted drink stock. The P&L does not run FIFO itself.

The row is recorded as `DailyPnLCogsRow.SALE`.

Example:

```text
POS Order SLE: -2 units, outgoing_rate=300
Drink COGS:     2 × 300 = 600
```

The test `test_drink_cogs_from_fifo` creates 100 drinks at 300, settles a 2-unit sale, and expects COGS of 600 (`test_compute.py:81-95`).

### Returns

The second query in `drink_cogs()` (`sources.py:109-129`) selects active positive `POS Return` SLEs inside the same datetime window. It calculates:

```text
return amount = returned quantity × SLE.incoming_rate
total COGS    = prior COGS - return amount
```

The detail row stores a negative amount and `kind=RETURN`.

The incoming rate is whatever the inventory return path supplied. In the current order service, `_restore_stock()` calls `StockLedgerEntry.create_entry()` without a rate, so the return can create a zero-rate FIFO layer. `drink_cogs()` therefore often sees `incoming_rate=0` for restocked POS returns. This is an inventory valuation issue that directly affects P&L return COGS.

### Non-restockable returns / wastage

For submitted return orders, `drink_cogs()` loops through return lines marked `not_restockable=True` (`sources.py:130-147`). These lines do not create a POS Return SLE. Instead, the report estimates their cost using `_wastage_rate()`:

1. Find the latest matching `POS Return` SLE, if any.
2. Otherwise find the latest negative source `POS Order` SLE and use its `outgoing_rate`.
3. Otherwise use the current Bin valuation rate.

Then:

```text
wastage amount = abs(return line qty) × selected rate
total COGS    += wastage amount
```

The detail row is `kind=WASTAGE`. This is added to COGS rather than treated as a restocked return.

## 8. Kitchen Consumption

### Source

`kitchen_consumption()` (`sources.py:150-165`) does not use the business-day datetime window. It filters exact calendar date:

```text
StockReconciliation.status="SUBMITTED"
StockReconciliation.reason="CONSUMPTION"
StockReconciliation.posting_date=DailyPnL.business_date
```

It then finds active negative SLEs with:

```text
voucher_type="Stock Reconciliation"
voucher_no in selected reconciliation PKs
actual_qty < 0
```

For every SLE:

```text
quantity = abs(actual_qty)
rate     = outgoing_rate
amount   = quantity × outgoing_rate
```

The total and detailed rows are returned to the computation.

### P&L treatment

The line is added as:

```python
LineSpec(
    DailyPnLLine.KITCHEN_CONSUMPTION,
    "Kitchen consumption",
    consumption,
    ZERO,
    consumption,
    is_memo=True,
)
```

It is FOOD-only in intended workflow and is displayed as a memo. It is not included in the gross-profit formula:

```text
gross profit = net sales - drink COGS - direct expenses
```

The test confirms that 10 units at FIFO cost 200 creates kitchen consumption of 2,000 while a 1,500 food sale still has gross profit 1,500 (`test_compute.py:97-130`).

## 9. Direct Expenses

Direct costs are accumulated in `direct_total`, with department-specific subcomponents for recurring templates and ad-hoc rows.

### Electricity

`electricity()` (`sources.py:180-188`) behaves as follows:

| Input | Result |
|---|---|
| Both readings blank | Zero; no electricity line is added |
| Only one reading supplied | Validation error |
| Closing below opening | Model validation error |
| Both supplied but configured rate <= 0 | Validation error |
| Both supplied and valid rate | `(closing - opening) × configured rate`, rounded to 2 places |

The configured rate comes from `PnLConfiguration.electricity_rate`, not from a stored rate on the draft. The line is added only if the amount is nonzero or readings were supplied (`services.py:108-113`).

### Manual materials

For every positive `DailyPnLMaterialQty` row:

```text
amount = qty × current PnLMaterial.rate
```

The line is DIRECT and source MATERIAL. Zero quantities are ignored. The calculation does not use `DailyPnLMaterialQty.rate` during preview; that field is only populated during submit.

### Recurring direct expenses

`PnLRecurringExpense` rows with kind `DIRECT_DAILY` become direct lines (`services.py:124-139`). The amount comes from `recurring_amount()`:

- daily kinds: configured amount;
- monthly kinds: amount divided by days in the month;
- percentage kind: percentage of gross sales.

Only direct-daily templates enter this first direct-expense loop. Their department determines whether the amount contributes to food, drinks, or total only.

### Ad-hoc direct expenses

Ad-hoc rows with `section=DIRECT` are added directly (`services.py:140-149`). Department splitting uses `_split()`:

```text
FOOD   -> amount_food=amount, amount_drinks=0
DRINKS -> amount_food=0, amount_drinks=amount
blank  -> amount_food=0, amount_drinks=0, amount_total=amount
```

## 10. Gross Profit

The implementation calculates three values:

```text
gross profit food   = food sales - direct food expenses
gross profit drinks = drink sales - drink COGS - direct drink expenses
gross profit total  = net sales - drink COGS - all direct expenses
```

Code: `apps/reports/services.py:151-154`.

Kitchen consumption is intentionally absent from the formula and is marked `is_memo=True`.

This means the displayed FOOD gross profit is not reduced by the cost of food consumed in the Kitchen. It reflects the documented/current design that food cost is shown as kitchen consumption rather than ordinary COGS.

## 11. Employee Costs and Prime Cost

### Employee costs

If `DailyPnL.employee_cost_override` is supplied, it completely replaces employee templates (`services.py:156-162`). The override is a total amount and is not department-split.

If no override is supplied, only recurring expenses with kinds:

- `EMPLOYEE_DAILY`
- `EMPLOYEE_MONTHLY`

are included (`services.py:163-175`). Their amount is computed using the same daily/monthly rules and may be split by department.

### Prime cost

```text
prime cost = drink COGS + total employee costs
```

The report adds Prime Cost as a memo line (`services.py:176-177`). It does not subtract prime cost again when calculating net profit. This avoids double counting because COGS and employee costs already enter the gross/net profit stages separately.

The test confirms Prime Cost is memo-only (`test_compute.py:259-266`).

## 12. Indirect Expenses

Indirect expense accumulation begins with:

```text
indirect total = employee costs + depreciation + cash variance
```

Then it adds recurring templates of kinds:

- `INDIRECT_DAILY`
- `INDIRECT_MONTHLY`
- `INDIRECT_PERCENT`

and ad-hoc rows with `section=INDIRECT` (`services.py:190-215`).

### Depreciation

`PnLConfiguration.daily_depreciation` is inserted as a flat daily amount (`services.py:179-183`). The model help text explicitly says it is not an asset schedule (`models.py:32-36`).

### Cash variance

`cash_variance()` (`sources.py:168-177`) selects submitted `POSClosingEntry` rows whose `period_end_date` lies inside the business window. It sums `total_short_excess`, then negates it:

```text
cash variance = -SUM(submitted closing total_short_excess)
```

Therefore:

- a shortage represented as negative `total_short_excess` becomes a positive expense;
- an excess becomes a negative expense/income-like adjustment.

The setting `include_cash_variance=False` forces zero. Tests cover both behaviors (`test_compute.py:240-257`).

## 13. Net Profit and Percentages

After all direct and indirect lines:

```text
net profit = gross profit - total indirect expenses
```

Code: `services.py:217-220`.

Every line percentage uses:

```text
percent_of_gross = amount_total / gross_sales × 100
```

with three decimal places. If gross sales is zero, the percentage is zero (`services.py:39-43`). This includes expense, memo, and net-profit rows, so memo lines can have percentages even though they are not included in the profit formula.

The `DailyPnL` total fields and percentages are populated from `Computation.totals` (`services.py:222-251`).

## 14. Preview Flow

### Form page preview

GET draft update:

```text
views.daily_pnl_update()
    -> compute_daily_pnl(pnl)
    -> render daily_pnl_form.html with preview
```

Code: `views.py:131-141`.

### Explicit HTMX/POST preview

```text
POST reports:daily_pnl_preview
    -> validate DailyPnLForm and both formsets
    -> transaction.atomic(): save parent and draft child inputs
    -> refresh pnl
    -> compute_daily_pnl(pnl)
    -> render _statement.html
```

Code: `views.py:160-189`.

Preview saves the submitted draft inputs before computing. It does not persist calculated lines or totals. A user can therefore preview a statement based on saved draft inputs while the live operational sources are queried at preview time.

## 15. Submit Flow and Persistence

### Entry point

```text
POST reports:daily_pnl_submit
    -> views.daily_pnl_submit()
    -> _require_manager()
    -> pnl.submit(actor=user)
    -> DailyPnL.submit()
    -> reports.services.submit_daily_pnl()
```

Code: `apps/reports/views.py:192-205`, `apps/reports/pnl_models.py:151-154`.

### Service sequence

`submit_daily_pnl()` (`services.py:256-308`) performs:

1. `SELECT FOR UPDATE` on the `DailyPnL` row.
2. Rejects anything other than DRAFT.
3. Calls `FiscalYear.get_for(business_date)` to ensure a fiscal year exists. This validates accounting-period configuration but does not post GL.
4. Loads current P&L configuration.
5. Recomputes the entire report from live sources and draft inputs.
6. Copies current `PnLMaterial.rate` into each material row and calculates its persisted amount.
7. Deletes any existing lines/detail rows for the draft.
8. Creates one `DailyPnLLine` per `LineSpec`.
9. Creates one `DailyPnLCogsRow` per COGS detail row.
10. Creates one `DailyPnLConsumptionRow` per kitchen-consumption detail row.
11. Copies all totals and percentages onto the parent `DailyPnL`.
12. Stores the current electricity rate and final period boundaries.
13. Sets status, submit timestamp, and submitting user.
14. Saves using the private `_allow_submit` lifecycle flag.

All of this is inside `@transaction.atomic`, so a failure rolls back the snapshot.

### Persisted statement structure

```text
DailyPnL
  ├── DailyPnLMaterialQty       input plus submitted rate/amount
  ├── DailyPnLAdHoc              input rows
  ├── DailyPnLLine                full statement rows
  ├── DailyPnLCogsRow             drink sale/return/wastage detail
  └── DailyPnLConsumptionRow      kitchen consumption detail
```

The detail rows are not recomputed on ordinary detail-page reads. The page reads the stored child rows (`views.py:145-156`).

## 16. Status, Cancellation, and Amendment

### Status rules

`DailyPnL` has DRAFT, SUBMITTED, and CANCELLED (`pnl_models.py:27-34`). Database constraints permit at most one draft and one submitted report per business date (`pnl_models.py:92-105`). Model validation additionally prevents a draft from existing alongside a submitted report for the same date (`pnl_models.py:125-130`).

Drafts can be edited/deleted. Submitted reports cannot be directly edited (`pnl_models.py:132-149`). Child material/ad-hoc rows also reject edits when the parent is not DRAFT.

### Cancellation

```text
POST daily_pnl_cancel
    -> views.daily_pnl_cancel()
    -> pnl.cancel()
    -> lock DailyPnL
    -> status=CANCELLED
    -> save with _allow_cancel
```

Code: `pnl_models.py:156-169` and `views.py:208-219`.

Cancellation does not reverse inventory, orders, COGS, payments, or GL. It changes only the report document status. The stored snapshot rows remain attached to the cancelled report.

### Amendment

Only a cancelled report can be amended (`pnl_models.py:171-194`). `amend()` creates a new DRAFT for the same business date, links it through `amended_from`, and copies:

- electricity readings;
- employee override;
- remarks;
- material quantities;
- ad-hoc rows.

It does not copy calculated totals, statement lines, COGS rows, or consumption rows. The new draft recomputes from current live sources when previewed/submitted.

This means an amendment can legitimately differ from the cancelled snapshot even if no manual inputs changed, because orders, SLEs, closings, or settings may have changed.

## 17. Detailed Numerical Example

Assume a business-day window contains:

| Source | Amount |
|---|---:|
| FOOD sales | 15,000 |
| DRINKS sales | 5,000 |
| Order rounding adjustment | -50 |
| Drink POS COGS | 1,500 |
| Kitchen consumption memo | 4,000 |
| Electricity | 500 |
| Manual cooking material | 200 |
| Direct daily expense | 300 |
| Employee costs | 2,000 |
| Depreciation | 100 |
| Cash shortage | 250 |
| Indirect expense | 400 |

The implementation calculates:

```text
Gross sales             = 15,000 + 5,000 = 20,000
Round-off               = -50
Net sales               = 19,950

Direct expenses         = 500 + 200 + 300 = 1,000
Gross profit            = 19,950 - 1,500 - 1,000 = 17,450

Prime cost memo         = 1,500 + 2,000 = 3,500

Indirect expenses       = 2,000 + 100 + 250 + 400 = 2,750
Net profit              = 17,450 - 2,750 = 14,700
```

Kitchen consumption of 4,000 is displayed separately but does not reduce gross profit or net profit. This is not an arithmetic omission in the code; it is explicitly represented as `is_memo=True` and excluded from both formulas.

## 18. Source-of-Truth Table

| P&L value | Source of truth | Read by | Snapshotted where |
|---|---|---|---|
| FOOD/DRINKS sales | Submitted `OrderItem.amount` | `sales_by_department()` | `DailyPnL` totals and `DailyPnLLine` |
| Round-off | Submitted `Order.rounding_adjustment` | `round_off()` | Parent total and line |
| Drink sale COGS | Active negative `POS Order` SLE `outgoing_rate` | `drink_cogs()` | Parent COGS and `DailyPnLCogsRow` |
| Drink return COGS reduction | Active positive `POS Return` SLE `incoming_rate` | `drink_cogs()` | COGS totals/detail |
| Return wastage | Return line plus `_wastage_rate()` | `drink_cogs()` | COGS detail |
| Kitchen consumption | Active negative consumption-reconciliation SLE `outgoing_rate` | `kitchen_consumption()` | Memo total and consumption rows |
| Electricity | Draft readings plus current config rate | `electricity()` | P&L line, stored rate, total |
| Manual material cost | Draft qty plus current `PnLMaterial.rate` | `compute_daily_pnl()` | Material row rate/amount and line |
| Daily/monthly/% expense | Enabled `PnLRecurringExpense` | `recurring_amount()` | Statement lines and totals |
| Cash variance | Submitted `POSClosingEntry.total_short_excess` | `cash_variance()` | Statement line and total |
| Depreciation | `PnLConfiguration.daily_depreciation` | `compute_daily_pnl()` | Statement line and total |
| Net profit | Computed formula | `compute_daily_pnl()` | Parent and final statement line |

## 19. Accounting Relationship

Daily P&L and accounting GL are separate in the current implementation.

### What the P&L reads from accounting-related data

- `submit_daily_pnl()` calls `FiscalYear.get_for()` to verify a fiscal year for the report date (`services.py:259-264`).
- Expense templates and P&L settings are report-owned, not GL journal lines.
- Drink COGS rate originates from inventory SLEs, while order settlement separately posts GL through `apps/accounting/services.py`.

### What the P&L does not do

- It does not create `GLEntry` rows.
- It does not create a `JournalEntry`.
- It does not reconcile its totals against GL.
- Cancelling it does not reverse GL.
- Amending it does not create an accounting reversal.

The test `test_submit_creates_no_gl` verifies this boundary. Therefore `DailyPnL.net_profit` is a management-report snapshot, not an accounting ledger balance.

## 20. Hidden and Non-Obvious Behavior

- `PnLConfiguration.load()` creates the singleton lazily if absent (`models.py:50-54`). A report computation can therefore create configuration state simply by being opened or previewed.
- Creating a Daily P&L seeds every enabled material as a zero-quantity child row (`views.py:40-45`).
- Preview saves draft form inputs before computing, so preview is not read-only with respect to draft input rows.
- Submission recomputes rather than trusting an earlier preview.
- Submission snapshots the current material rates. A material-rate change after submission does not alter that submitted report.
- Submitted P&L rows are not independently protected by `save()` overrides. Parent lifecycle guards prevent ordinary edits through the workflow, but direct ORM/admin changes remain a possible bypass unless admin configuration prevents them.
- `DailyPnLLine`, `DailyPnLCogsRow`, and `DailyPnLConsumptionRow` use `CASCADE` from the parent. Deleting a draft cascades child rows; submitted/cancelled parent deletion is blocked by `DailyPnL.delete()`.
- `orders_in_window()` filters by `Order.posting_date` before checking the combined posting date/time. It does not use `submitted_at`.
- Drink COGS uses SLE `posting_datetime`, which is SLE creation time. Revenue uses order `posting_date`/`posting_time`. These timestamps can differ.
- Kitchen consumption uses reconciliation `posting_date` exactly, not the configured business-day window.
- Department values for revenue come from the historical `OrderItem.department` snapshot, not the current `Item.department`.
- COGS rows and consumption rows are written in their source-query order, while their models define their own display ordering.

## 21. Risks and Inconsistencies

### High: P&L can use different time semantics for revenue, COGS, and kitchen consumption

Revenue is filtered by order posting date/time, drink COGS by SLE creation datetime, and kitchen consumption by reconciliation calendar `posting_date`. A transaction posted at a boundary can therefore appear in one P&L component but not another.

### High: P&L snapshot can disagree with GL

The report is not derived from GL and does not post GL. Accounting order settlement can include COGS and revenue legs that are not necessarily selected by the same timestamp rules as the report. There is no reconciliation check between `DailyPnL` and `GLEntry`.

### High: Return valuation can be zero or inconsistent

`orders.services._restore_stock()` creates positive return SLEs without passing a rate. `drink_cogs()` uses that SLE's `incoming_rate` to reduce COGS, so a restocked return can reduce COGS by zero even when the original sale had a nonzero FIFO cost.

### Medium: Food cost is a memo, not a profit expense

Food kitchen consumption is calculated and displayed, but excluded from gross profit and net profit. This produces a management presentation in which food margin is not a conventional food gross margin.

### Medium: Configuration changes affect drafts and amendments

Preview and submission read current electricity rate, depreciation, recurring expenses, and material rates. A draft opened on one day and submitted later can change materially without changing its manual inputs. Submitted reports are stable afterward.

### Medium: Cash variance can be duplicated or omitted based on closing period

The report sums all submitted closings whose `period_end_date` is in the business window. There is no explicit link between a Daily P&L and a particular shift close, and no guard against multiple closings contributing to the same report beyond the source status/date filter.

### Medium: Material rows snapshot rate only on submit

The stored `DailyPnLMaterialQty.rate` and `amount` can remain stale/zero while a report is a draft. Any consumer reading those fields before submission must not interpret them as the current computed cost; preview uses `PnLMaterial.rate` instead.

### Medium: Direct ORM changes can bypass report immutability

`editable=False` and view guards are not database constraints. Direct `QuerySet.update()`, admin actions, or low-level saves can alter submitted totals or child rows without recomputation.

### Low: Percentages are percentages of gross sales, not net sales

Every percentage uses `gross` as denominator, including `net_sales_percent` and `net_profit_percent`. This is consistent in code but easy to misread as a net-sales margin.

### Low: `FiscalYear.get_for()` is a validation dependency, not a posting dependency

A fiscal year must exist to submit the report, but no journal entry is created. This can make the report appear more tightly coupled to accounting than it actually is.

## 22. Complete End-to-End Example

```text
Manager chooses business date
    ↓
DailyPnL draft is created
    ↓
P&L period is calculated from business_day_start_hour
    ↓
Enabled materials are seeded with qty=0
    ↓
Manager enters electricity readings, material qty, ad-hoc costs,
and optionally employee override
    ↓
Preview saves those draft inputs and computes from live sources
    ↓
Submitted orders in the business window provide revenue
    ↓
POS drink SLEs provide FIFO outgoing COGS
    ↓
POS return SLEs reduce COGS; non-restockable returns add wastage
    ↓
Kitchen CONSUMPTION reconciliation SLEs create a FOOD memo
    ↓
Settings/templates/manual inputs add direct, employee, and indirect costs
    ↓
Gross profit and net profit are calculated
    ↓
Submit recomputes once more inside an atomic transaction
    ↓
DailyPnL totals and child snapshot rows are written
    ↓
DailyPnL becomes SUBMITTED
    ↓
No GL entry is created
```

## 23. Final Mental Model

1. **What is a Daily P&L?** A dated, manager-submitted snapshot document.
2. **What determines its day?** `PnLConfiguration.business_day_start_hour` creates a 24-hour `[start,end)` window.
3. **Where does revenue come from?** Submitted `OrderItem.amount`, grouped by the stored FOOD/DRINKS department.
4. **Where does drink COGS come from?** Negative `POS Order` SLEs and their FIFO-generated `outgoing_rate`.
5. **How are returns handled?** Positive `POS Return` SLEs reduce COGS; non-restockable return lines add wastage using a fallback rate chain.
6. **How is food cost handled?** Submitted Kitchen `CONSUMPTION` reconciliation SLEs become a memo and do not reduce profit.
7. **Where do electricity/material/other costs come from?** Draft inputs, P&L materials, recurring templates, ad-hoc rows, depreciation settings, and shift closings.
8. **What is gross profit?** Net sales minus drink COGS minus all direct expenses.
9. **What is net profit?** Gross profit minus employee costs, depreciation, cash variance, and indirect expenses.
10. **What does Prime Cost mean here?** A memo equal to drink COGS plus employee costs; it is not subtracted separately.
11. **When does data become permanent?** On submit, calculated totals and child detail rows are stored and the document becomes immutable through normal model workflows.
12. **What does cancellation do?** Changes only P&L status; it does not reverse inventory or accounting.
13. **What does amendment do?** Creates a new draft with copied manual inputs and recomputes against current live data.
14. **Is it an accounting statement?** No. It is a management report snapshot with no GL posting or GL reconciliation.

# Accounting Scope Recommendations

⚠️ **Proposed scope review, not implemented behavior.** This page records the
eight accounting capabilities recommended after reviewing Phase 8 against normal
single-location restaurant accounting practice. It does not change the current
implementation or lock a future phase until the scope is approved.

> **Approved 2026-08-16 (partial):** four of the eight capabilities were adopted into
> `PLAN.md` §3 and §6.25–§6.28 as Phases 13–16 — opening balances & go-live setup, trial
> balance & financial statements, cash shortage & excess posting, supplier payables &
> invoices. The adopted scope is exactly what each `PLAN.md` stub describes; it is fixed, not
> an upgrade/downgrade path, and no app setting controls it. The other four capabilities
> (bank reconciliation, period lock, fixed assets, year-end closing) remain proposed only.

The review excludes tax accounting, customer receivables, and credit sales as
requested. Inventory-document GL and return/refund GL are already assigned to
later phases in `PLAN.md` and are not repeated here.

## Classification

The recommendations are split into two categories:

| Category | Meaning |
|---|---|
| Extension of planned work | An existing planned feature is incomplete for accounting without this addition. |
| New accounting feature | A useful accounting capability that is not currently part of a planned phase. |

### Extensions of Planned Work

| Feature | Related existing work | Priority |
|---|---|---|
| Cash shortage and excess posting | Staff shift closing and Phase 8 GL | High |
| Bank and electronic-payment reconciliation | Payment modes, PaymentGLMapping, and shift closing | High |
| Opening balances and go-live setup | POS opening entries and Phase 8 JournalEntry | High |
| Trial balance and financial statements | Phase 8 GL and Phase 10 reports | High |
| Supplier payables and supplier invoices | Phase 9 purchase and inventory accounting | High when suppliers allow payment later |

### New Accounting Features

| Feature | Why it is separate | Priority |
|---|---|---|
| Accounting period lock | Fiscal years define dates but do not close reviewed periods | Medium to high |
| Fixed asset register and depreciation | Daily P&L mentions depreciation, but no asset accounting workflow exists | Medium |
| Year-end equity closing | Fiscal years exist, but formal transfer of annual profit or loss is not specified | Medium |

## Activation Policy

The system should support a **Basic** and **Full** accounting mode rather than a
single switch that turns accounting off.

Basic mode should retain the accounting entries that are necessary for the POS
to remain financially coherent:

- Settled order sales entries.
- Payment account entries.
- COGS and stock entries when stock is tracked.
- Cancellation reversals.
- A small set of manual Journal Entry types.

Basic mode may leave these optional workflows inactive:

- Bank reconciliation.
- Automated cash over/short posting, if variances are reviewed and posted manually.
- Supplier credit and payable management.
- Fixed asset schedules.
- Period locking.
- Automated year-end closing.

An `accounting_enabled=False` switch that silently allows live orders without
GL entries is not recommended. It would create a gap between operational sales
and the accounting history, and later activation would not reconstruct the
missing entries safely. If the business uses a separate accounting system, that
should be an explicit integration or export mode with clear ownership of the
books, not an unlabelled switch.

Optional features should be activated from a manager-only Restaurant settings
surface. Enabling a feature later should affect new transactions from its
activation date; historical data should only be marked reconciled or migrated
when the business has enough source evidence to do so.

## 1. Cash Shortage and Excess Posting

### Concept

At shift close, the system compares the amount expected in the cash drawer with
the amount actually counted. A shortage means less cash was found than the
ledger expects. An excess means more cash was found.

### Why it is needed

The current close workflow calculates the variance operationally. Without a GL
adjustment, the Cash Account remains at the expected amount even when the
physical drawer differs. The ledger and the real cash position then disagree.

This is a standard cashier-control feature and is especially important when
multiple staff use one shared shift.

### Proposed implementation

Add configurable ledger accounts for `Cash Shortage Expense` and `Cash Over / Short
Income`, or use one account with a sign-aware presentation. When a submitted
shift close has a non-zero approved variance, create a Journal Entry or a
dedicated shift-variance posting linked to the closing entry.

For a shortage of NGN 2,000:

```text
Debit   Cash Shortage Expense       NGN 2,000
Credit  Cash Account                NGN 2,000
```

For an excess of NGN 2,000:

```text
Debit   Cash Account                NGN 2,000
Credit  Cash Over / Short Income    NGN 2,000
```

The posting must be atomic with the approved close, immutable after posting,
and reversible if the closing entry is cancelled. Material variances should
require manager approval or a required explanation.

### Problem solved

The GL cash balance matches the physical drawer after reconciliation, and
shortages or excesses become visible expenses or income instead of unexplained
differences.

### Can it be added after go-live?

Yes. The core Order and GL structures do not need to change. It can be enabled
for new shift closes. Historical variances can be posted only if the business
has reviewed the old closing records.

It is preferable to have the account configuration and posting hook before
go-live if the business wants every shift to be fully accounted for from day
one.

### Basic mode

The business can leave automatic variance posting off while continuing to show
the variance on the close. A manager can post an occasional adjustment through
a Journal Entry. This is acceptable for a very small operation, but the
variance must not be hidden.

## 2. Bank and Electronic-Payment Reconciliation

### Concept

Bank reconciliation compares electronic payments recorded by RestPOS with the
amounts that actually appear in bank or payment-provider statements.

Cashier close reconciles a drawer. It does not prove that a card, bank-transfer,
or payment-terminal transaction reached the bank.

### Why it is needed

PaymentGLMapping identifies the account used when a payment is recorded, but it
does not confirm settlement. Electronic payments can be delayed, rejected,
duplicated, settled net of fees, or deposited in batches.

Without reconciliation, an Electronic or Card Clearing account can accumulate a
balance that nobody has explained.

### Proposed implementation

Use a clearing account for payment methods whose funds settle later. Add a
reconciliation record that can match one or more RestPOS payment rows to one or
more imported or manually entered bank statement rows.

A card payment of NGN 10,000 settled after a NGN 300 provider fee could be
recorded as:

```text
At sale:
Debit   Card Clearing Account       NGN 10,000
Credit  Sales Account               NGN 10,000

At bank settlement:
Debit   Bank Account                 NGN 9,700
Debit   Payment Processing Expense     NGN 300
Credit  Card Clearing Account       NGN 10,000
```

The feature should support unmatched, partially matched, and fee-adjusted
settlements. It should preserve the source payment and bank references rather
than editing the original payment rows.

### Problem solved

The restaurant can prove that recorded electronic sales reached the bank,
explain payment-provider deductions, and identify missing or duplicate
settlements.

### Can it be added after go-live?

Yes. This is an additive workflow around existing payment and GL records. It
can begin from a chosen activation date. Historical transactions can be
reconciled later, but automatic matching may require importing old statements.

The payment account design should distinguish direct bank payments from
clearing-account payments before the first electronic transactions if accurate
historical reconciliation is important.

### Basic mode

Leave the reconciliation screen inactive. Electronic payments may still post to
their configured account, but the account should be labelled as unreconciled
and reviewed externally. This is suitable only when the volume is low and the
owner checks bank statements outside RestPOS.

## 3. Opening Balances and Go-Live Setup

### Concept

Opening balances describe what the business owns, owes, and has invested at the
moment RestPOS becomes the accounting source of truth.

Typical opening balances include cash, bank funds, stock, equipment, supplier
balances, and owner equity.

### Why it is needed

If the system starts with zero balances while the restaurant already has cash,
stock, equipment, or bank funds, the first balance sheet and account statements
will be wrong. The POS can record new sales correctly while still producing an
incorrect overall financial position.

### Proposed implementation

Use the planned `JournalEntry.is_opening` and `OPENING` voucher type for a
manager-controlled opening-balance workflow. Require:

- One selected opening date.
- A balanced opening Journal Entry.
- A clear source or note for each balance.
- Protection against accidental duplicate opening sets.
- A review and submit action before the opening becomes effective.

For example:

```text
Debit   Cash Account                 NGN 200,000
Debit   Bank Account                 NGN 800,000
Debit   Stock-in-Hand                NGN 500,000
Debit   Equipment Asset            NGN 1,000,000
Credit  Owner's Equity              NGN 2,500,000
```

### Problem solved

The ledger starts from the restaurant's real financial position instead of
pretending that the business had no prior activity.

### Can it be added after go-live?

The workflow can be added later, but accurate opening balances should be
completed before go-live if RestPOS is intended to be the main accounting
record. Adding them later requires a dated adjustment and may change previously
reported balances.

This is the one feature in this document that should normally be treated as a
go-live prerequisite for an existing restaurant.

### Basic mode

Use one reviewed opening Journal Entry instead of a dedicated import wizard.
That keeps the feature simple without omitting the opening position. A business
should not turn opening balances off and then treat RestPOS balance-sheet
reports as complete.

## 4. Trial Balance and Financial Statements

### Concept

The General Ledger stores detailed entries. Financial statements summarize those
entries into reports that management can use and verify.

The minimum accounting reports are:

- Trial Balance.
- Profit and Loss Statement.
- Balance Sheet.
- Account statement.
- General Ledger report.

### Why it is needed

An entry list does not show whether the business is profitable, what it owns, or
whether the ledger is internally consistent. The planned Daily P&L is a useful
management report, but it is not a replacement for a formal accounting P&L,
trial balance, or balance sheet.

### Proposed implementation

Build read-only reports from `GLEntry` grouped by account, fiscal year, posting
date, and cost center.

The Trial Balance should show opening debit or credit, period movement, and
closing debit or credit. The Profit and Loss Statement should use income and
expense accounts. The Balance Sheet should use asset, liability, and equity
accounts.

Every report should be able to drill down to the source voucher and its GL
entries. Cancelled entries and their reversals must be handled consistently.

### Problem solved

The owner can verify the books, find unexplained balances, see profit, and
understand the restaurant's financial position without exporting raw ledger rows
to another system.

### Can it be added after go-live?

Yes. These are primarily read-only queries over the existing GL structure. They
can be added after the restaurant is running without changing Order or payment
data. Historical reports will still be limited by whatever accounts and opening
balances were configured at the time.

The Trial Balance should be available as soon as Phase 8 GL posting is live,
even if the richer statements are delivered later.

### Basic mode

Reports should not be disabled. A basic mode can provide only General Ledger,
Trial Balance, and a simple Profit and Loss report. These are low-risk,
read-only outputs and are necessary to check that the accounting system is
balanced.

## 5. Accounting Period Lock

### Concept

A fiscal year says which dates belong to a reporting year. A period lock says
that a reviewed period must not be changed by ordinary users.

For example, after July is reviewed, a new order cancellation or Journal Entry
should not silently change July's results.

### Why it is needed

Without a lock, a previously issued report can change whenever someone creates,
cancels, or backdates a document. A `FiscalYear` model alone does not provide
this control.

### Proposed implementation

Add a manager-controlled closed-through date, either on the Restaurant settings
surface or in a dedicated accounting-period model. Posting, cancellation, and
reversal services should reject dates on or before the lock unless the user has
an explicit override permission.

The system should record:

- Who closed the period.
- When it was closed.
- Who reopened or overrode it.
- Why an override was allowed.

The rule must be enforced in services, not only in forms.

### Problem solved

Reviewed reports remain stable, and backdated corrections become visible,
authorized accounting events instead of silent data changes.

### Can it be added after go-live?

Yes. The control is additive and can be enabled when the first reporting period
has been reviewed. Existing documents do not need to be restructured.

It should be enabled before the business relies on historical reports for
management or statutory purposes.

### Basic mode

Leave period locks inactive and rely on manager permissions and fiscal-year
validation. This is reasonable for a very small operation, but every backdated
correction should still have a clear Journal Entry remark.

## 6. Supplier Payables and Supplier Invoices

### Concept

Accounts Payable records money the restaurant owes suppliers. This is different
from customer receivables and credit sales, which are intentionally excluded
from this review.

A Purchase Receipt confirms that goods arrived. A supplier invoice confirms what
the supplier is charging. Payment later clears the payable.

### Why it is needed

Restaurants commonly receive food, drinks, gas, packaging, and cleaning
supplies before paying the supplier. A purchase receipt that only increases
stock does not show the liability or when it was paid.

If supplier credit is never used, a direct cash purchase entry may be enough.
If it is used, payable accounting is necessary for accurate cash planning and
supplier balances.

### Proposed implementation

Extend the planned purchase and inventory accounting with:

- A Supplier master record.
- Supplier invoice or purchase-bill documents.
- Invoice lines linked to received stock or expenses.
- Accounts payable balance.
- Supplier payment entries.
- Allocation of payments to invoices.
- Cancellation and reversal rules.

For a supplier invoice:

```text
Debit   Inventory / Stock-in-Hand     NGN 100,000
Credit  Accounts Payable              NGN 100,000
```

When paid:

```text
Debit   Accounts Payable              NGN 100,000
Credit  Bank Account                  NGN 100,000
```

The existing `supplier_name` text on a receipt is not enough to provide this
workflow. The supplier identity and payable documents should be separate from
the stock receipt lifecycle.

### Problem solved

The restaurant knows what it owes each supplier, which invoices are unpaid, and
whether stock purchases were paid by cash, bank, or supplier credit.

### Can it be added after go-live?

Yes, if all purchases before activation were cash purchases or were maintained
in another accounting system. It should be added before the first supplier
credit transaction that RestPOS is expected to track.

Existing unpaid supplier balances can be imported as opening payables, but
historical purchase receipts without prices or invoice references cannot be
reconstructed reliably.

### Basic mode

Do not enable supplier credit in RestPOS. Record only cash or bank purchases
through inventory accounting or manual Journal Entries. If the business later
starts buying on credit, it can activate supplier payables from that date.

## 7. Fixed Asset Register and Depreciation

### Concept

A fixed asset is a durable item used by the business for more than one accounting
period, such as a freezer, generator, oven, or POS terminal.

Depreciation spreads the asset's cost over its useful life rather than treating
the entire purchase as a single period expense.

### Why it is needed

The planned Daily P&L mentions depreciation, but a daily depreciation amount is
not the same as maintaining the underlying asset accounting. Without an asset
register, the business cannot reliably answer:

- What equipment does it own?
- When was it purchased?
- What is its remaining book value?
- How much depreciation has been recorded?

### Proposed implementation

Add an Asset model with:

- Asset name and category.
- Purchase date and cost.
- Supplier or source reference.
- Useful life.
- Depreciation method.
- Residual value.
- Accumulated depreciation.
- Disposal or write-off status.

At purchase:

```text
Debit   Equipment Asset             NGN 1,200,000
Credit  Cash or Accounts Payable    NGN 1,200,000
```

Monthly depreciation:

```text
Debit   Depreciation Expense           NGN 50,000
Credit  Accumulated Depreciation       NGN 50,000
```

The generated accounting entries must use the same immutable submit and
reverse pattern as other financial documents.

### Problem solved

The restaurant's profit and asset values reflect the use of long-lived
equipment, and management can see the remaining value of major assets.

### Can it be added after go-live?

Yes. It is additive and can begin from an activation date. Existing equipment
can be imported with an agreed opening book value and accumulated depreciation.
That import requires reliable purchase records or an accountant-approved
valuation.

It is not a prerequisite for starting a POS if depreciation is handled outside
RestPOS initially.

### Basic mode

Leave the asset schedule inactive. Record material equipment purchases and
periodic depreciation through manual Journal Entries or an external accounting
system. The Daily P&L should label any manually entered depreciation clearly.

## 8. Year-End Equity Closing

### Concept

At year end, the net result from income and expense accounts is transferred to
retained earnings or owner equity. This separates one fiscal year's operating
result from the next year's activity.

### Why it is needed

Fiscal years can exist without an automated year-end closing process, but formal
annual reporting eventually needs a clear treatment of accumulated profit or
loss.

Without closing, income and expense balances can continue accumulating across
years, making annual reports dependent on date filters rather than a clean
year-end process.

### Proposed implementation

Add a manager-controlled year-end closing action that:

- Confirms the fiscal year is complete.
- Calculates the net income or loss.
- Creates a balanced closing Journal Entry.
- Transfers the result to Retained Earnings or Owner's Equity.
- Marks the fiscal year as closed.
- Prevents ordinary backdated postings.

The process must not delete or edit the original income and expense entries.
It should be reversible only through a controlled reopening or reversal flow.

### Problem solved

Annual profit is carried into equity in a controlled, auditable way, and the
next fiscal year begins with clean income and expense reporting.

### Can it be added after go-live?

Yes. It can be implemented before the first year-end close. It does not need to
exist on the first day of POS operation, but it should be available before the
business treats its first fiscal year as finalized.

If added mid-year, the business should first agree with its accountant whether
the current year's balances remain open or whether an interim closing entry is
appropriate.

### Basic mode

Do not automate the process. Keep the fiscal year open and have an accountant
post a manual closing Journal Entry or perform the close in an external system.
This is acceptable for a basic operation, provided the owner understands that
RestPOS is not performing formal year-end closing.

## Go-Live and Later-Activation Matrix

| Feature | Strictly before go-live? | Safe to add later? | Historical limitation |
|---|---:|---:|---|
| Cash shortage/excess posting | Recommended | Yes | Old variances need review before back-posting |
| Bank reconciliation | No | Yes | Old statements need importing and matching |
| Opening balances | Yes if RestPOS is the accounting source | Partially | Later entry changes the starting financial position |
| Trial balance/statements | Recommended before trusting reports | Yes | Reports cannot correct missing opening balances |
| Period lock | No | Yes | Previously changed periods may need review |
| Supplier payables | Before first credit purchase | Yes | Old supplier balances need an opening import |
| Fixed assets/depreciation | No if handled externally | Yes | Old assets require approved opening values |
| Year-end equity closing | Before first finalized year end | Yes | Mid-year activation needs an accounting decision |

## Recommended Product Decision

For a basic single-location restaurant, the minimum accounting foundation should
include:

- Order-level sales GL.
- Payment and COGS GL.
- Cancellation reversals.
- Opening balances.
- Cash variance visibility, with optional automatic posting.
- Trial Balance and basic Profit and Loss reports.

The following can be activated later without changing the core order data model:

- Bank reconciliation.
- Period locks.
- Supplier payables, provided supplier credit is not used before activation.
- Fixed assets.
- Year-end closing.

The recommended design is additive feature activation, not a full accounting
off switch. Core sales accounting should remain consistent once the system has
started posting financial transactions.

I need you to walk me through **exactly how inventory stock movement works in this codebase**, from the moment stock is added to the system until it is eventually deducted, including the relationship between stock entries, Stock Ledger Entries (SLE), stock queues, FIFO, bin balances, transfers, and purchase receipts.

The goal is not just to understand the business logic. I want to understand **the actual implementation down to the code level**.

### 1. Start with the inventory architecture

First, identify and explain all the models, services, functions, signals, repositories, or other components involved in inventory stock management.

For each important component, explain:

* What it represents
* Why it exists
* What other components it interacts with
* Which component is the source of truth for each type of inventory information
* Where stock quantities, valuation, and FIFO information are persisted

Show the relevant file paths and code sections as you explain them.

### 2. Explain stock addition from beginning to end

Trace what happens when inventory enters the system.

Cover at least:

* Purchase Receipt
* Stock Entry for receipt/addition
* Stock Entry for transfer
* Any other mechanism that can increase stock

For each flow, trace the execution **chronologically through the actual code**:

```text
User action
    ↓
View
    ↓
Service
    ↓
model operations
    ↓
SLE creation
    ↓
Bin update
    ↓
Stock queue/FIFO update
```

Do not assume this sequence is correct. Determine the actual sequence from the code.

For every step, identify:

* The function/method being called
* The file where it is located
* Important parameters passed
* Database records created or modified
* Why the operation happens at that point

### 3. Explain Stock Ledger Entries (SLE) in detail

Explain exactly what an SLE represents in this codebase.

Cover:

* The SLE model
* Every important field
* How positive and negative quantities are represented
* How incoming and outgoing stock are recorded
* How valuation/rate/value is recorded
* How timestamps/order are determined
* How SLEs are linked to their source transactions
* Whether SLEs are immutable or can be modified/reposted
* How cancellations/reversals work
* How historical SLEs affect current stock

Then trace several concrete examples through the code.

### 4. Explain stock deduction

Trace exactly what happens when stock is consumed.

Include:

* Sales
* Stock transfers
* Stock issues
* Any other stock deduction mechanism in the codebase

Explain the complete chain from the transaction to the final stock deduction.

I specifically want to understand **how the system decides which stock is being deducted**.

For example:

```text
Available stock:
Receipt A → 10 units @ ₦100
Receipt B → 15 units @ ₦120
Receipt C → 20 units @ ₦130

Sale → 18 units

Which quantities are deducted?
Which receipt layers are affected?
Where is this information stored?
How it is stored in the ui
What happens to the remaining quantities?
```

Use an example like this and map every step to the actual implementation.

### 5. Explain the stock queue

Identify exactly what the codebase means by **stock queue**.

Explain:

* What model/data structure represents it
* What each queue entry represents
* When entries are created
* When they are consumed
* When they are modified
* How quantities are tracked
* How the queue relates to SLE
* How the queue relates to Bin
* How the queue relates to FIFO

Determine whether the queue is:

* The actual source of truth for FIFO
* A derived structure
* A cache
* A valuation mechanism
* Or something else

Do not infer this from naming. Determine it from the implementation.

### 6. Explain FIFO completely

Trace the actual FIFO implementation.

Explain:

* How receipt layers are created
* How they are ordered
* How the oldest layer is identified
* How a deduction consumes a layer
* What happens when one layer is insufficient
* How multiple layers are consumed
* How remaining quantities are persisted
* How valuation is calculated
* What happens when stock is returned
* What happens when a transaction is cancelled
* What happens when historical transactions are inserted or changed

Use a detailed numerical example and show the state of the FIFO layers after every transaction.

### 7. Explain Bin stock

Explain exactly what **Bin** represents in this implementation.

Cover:

* The Bin model
* Its important fields
* How it is created
* How it is updated
* What triggers updates
* Whether it stores current quantity, projected quantity, valuation, or something else
* How its values relate to SLE
* How its values relate to FIFO/stock queues
* Whether Bin can be rebuilt from SLE
* What happens if Bin becomes inconsistent with the ledger

Then trace an actual stock addition and deduction and show the Bin values before and after each operation.

### 8. Compare SLE, Bin, Stock Queue, FIFO, and source transactions

Give me a clear distinction between these concepts.

Use a table such as:

| Component | Purpose | Source of truth? | Stores quantity? | Stores valuation? | Used for FIFO? | Updated when? |
| --------- | ------- | ---------------- | ---------------- | ----------------- | -------------- | ------------- |

Then explain the relationships between them.

I want to eliminate any confusion about why the system needs all of these structures instead of simply calculating stock directly from transactions.

### 9. Trace Purchase Receipt specifically

Walk through a **Purchase Receipt** from creation to final inventory state.

Show:

```text
Purchase Receipt
    ↓
Purchase Receipt Items
    ↓
Stock transaction
    ↓
SLE
    ↓
Bin
    ↓
FIFO / Stock Queue
```

Again, verify the actual sequence from the code rather than assuming it.

Explain what happens if:

* A purchase receipt is cancelled
* A purchase receipt is amended
* Part of the received quantity is later sold
* The entire quantity is later sold
* The purchase receipt is created after other transactions already exist

### 10. Trace Stock Entry specifically

Explain every relevant Stock Entry type separately.

At minimum:

* Material receipt/addition
* Material issue/deduction
* Transfer

For transfers, explain **both sides of the transfer**.

For example:

```text
Warehouse A
    ↓
Transfer
    ↓
Warehouse B
```

Explain:

* What happens to Warehouse A's stock
* What happens to Warehouse B's stock
* How many SLEs are created
* How FIFO layers move between warehouses
* Whether the original receipt layer is preserved
* Whether a new FIFO layer is created at the destination
* How Bin records change
* How the system prevents stock from being duplicated during transfer

### 11. Trace cancellation and reversal

Explain how cancellation works at the inventory level.

I want to understand:

* Whether the original SLE is deleted
* Whether a reversal SLE is created
* How the reversal affects Bin
* How the reversal affects FIFO/stock queue
* How historical stock calculations behave
* How the system prevents double-counting

Use a concrete example:

```text
Receipt: +100
Sale:    -30
Cancel receipt: +?
```

Show the exact resulting SLEs, Bin balance, and FIFO state.

Also identify any subtle cases where a reversal can affect historical stock calculations or FIFO valuation incorrectly.

### 12. Trace one complete lifecycle

After explaining the individual components, trace one item through its entire lifecycle.

For example:

```text
Purchase 100 units
        ↓
Receive 100
        ↓
Transfer 40 to Warehouse B
        ↓
Sell 20 from Warehouse A
        ↓
Sell 10 from Warehouse B
        ↓
Receive another 50
        ↓
Sell 80
        ↓
Cancel one transaction
```

At every stage show:

* SLE records
* Bin quantity
* FIFO/stock queue layers
* Quantity remaining
* Which receipt layers were consumed
* The resulting valuation where applicable

### 13. Explain the actual code, not just the concepts

For every important behavior, point me to the actual implementation.

Use this format where useful:

```text
Behavior:
    FIFO deduction

Implemented in:
    path/to/file.py

Entry point:
    function_name()

Calls:
    function_a()
        → function_b()
            → function_c()

Database changes:
    Model A: created
    Model B: updated
    Model C: created

Why:
    Explanation
```

Quote only the relevant small portions of code when necessary. Do not dump entire files.

If a function calls another function, follow the call chain until we reach the actual database mutation or core inventory calculation.

### 14. Identify hidden or non-obvious behavior

While investigating, explicitly point out:

* Implicit behavior
* Django signals
* Model `save()` overrides
* Managers/querysets
* Transactions
* Database constraints
* Background jobs
* Event handlers
* Cached/derived values
* Any code that updates inventory indirectly
* Any places where the same inventory quantity can be changed through different paths

I especially want to know about behavior that is easy to miss when reading the main service functions.

### 15. Identify inconsistencies and risks

Do not assume the implementation is correct.

If you find:

* Inconsistent stock calculations
* Possible race conditions
* FIFO inconsistencies
* SLE/Bin synchronization problems
* Cancellation/reversal problems
* Duplicate stock updates
* Missing transaction boundaries
* Incorrect handling of historical transactions
* Possible negative stock problems
* Valuation inconsistencies

point them out explicitly.

For each issue, explain the exact code path that creates the risk.

### 16. Final mental model

Finish with a concise mental model of the entire inventory system.

I should be able to answer these questions after reading your explanation:

1. **Where does stock physically enter the system?**
2. **What record represents that event?**
3. **What creates the SLE?**
4. **What updates the Bin?**
5. **What creates the FIFO/stock queue layer?**
6. **When stock is sold, what code finds the stock to deduct?**
7. **How does FIFO determine which layer is consumed?**
8. **Where is the remaining quantity stored?**
9. **How does a transfer move stock between warehouses?**
10. **How do cancellation and reversal affect every inventory structure?**
11. **Which structure is authoritative when two structures disagree?**
12. **Can the entire current inventory state be reconstructed from the ledger?**

### Important instructions

* **Base the explanation strictly on the codebase.**
* Do not give me a generic explanation of inventory systems unless it is necessary to explain something found in the code.
* Do not skip intermediate functions just because they appear obvious.
* Follow the actual call chain.
* Use file paths, class names, function names, and model names throughout.
* Distinguish clearly between **what the code actually does** and **what you think it should do**.
* If something cannot be determined from the available code, say so explicitly.
* If there are multiple inventory paths that behave differently, explain each one separately.
* Use concrete quantities and ledger examples whenever they make the flow easier to understand.
* Start from the lowest-level architecture and progressively build toward the complete inventory lifecycle.
* Do not try to explain the entire codebase at once if that would make the explanation difficult to follow. Break it into logical sections and build the mental model progressively.



Put your reponse in a .md file

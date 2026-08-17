# Glossary

| Term | Meaning in the current code |
|---|---|
| Restaurant | Singleton `settings.Restaurant` configuration row for identity, active menu, warehouses, and POS limits. |
| Production Unit | `settings.ProductionUnit` station for FOOD or DRINKS with a warehouse and printer metadata. |
| Item | Inventory master record used for both sellable products and internal stock. |
| Menu | Named enabled collection of priced `MenuItem` rows. |
| Menu Item | A priced link between a Menu and an inventory Item. Its rate is the POS selling price. |
| Add-on | Separate sellable Item linked through `ItemAddOn` and added as its own order line. |
| Variant | Inventory Item linked to a parent through `ItemVariant`; modeled but not selected through the current POS UI. |
| Department | `FOOD` or `DRINKS`; controls production routing and the DRINKS-only POS stock policy. |
| Warehouse | Stock location. Its operational role comes from Restaurant/ProductionUnit references, not a type field. |
| Bin | Current item/warehouse snapshot of actual, reserved, and valued stock. |
| Stock Ledger Entry / SLE | Signed immutable-by-convention movement row with running quantity and FIFO queue. |
| Stock Entry | Draft document for Material Receipt or Store-to-production transfer. |
| Stock Reconciliation | Draft count/adjustment document with a structured reason. |
| Purchase Receipt | Draft supplier receipt into the central Store warehouse. |
| Shift | The globally shared `POSOpeningEntry` period, closed by `POSClosingEntry`. |
| Opening Payment | Payment-mode opening balance for a shift. |
| Closing Payment | Payment-mode counted, expected, and variance values at shift close. |
| Mode of Payment | Configurable payment method master, such as Cash or Bank. |
| GL Mapping | `PaymentGLMapping` account-name mapping required for settlement. |
| Order | Operational POS document containing lines, payments, status, totals, and audit events. |
| Draft | Editable order state before settlement, a KOT, cancellation, or deletion. |
| Order Item | Historical line snapshot with item, price, quantity, department, comments, and customer index. |
| Customer Card | Ephemeral POS session selection represented by an integer customer index; not a customer model. |
| Guest Count | `Order.guest_count`, from 1 to 50, used to render customer groups. |
| Customer Index | `OrderItem.customer_index`, a 1-based persistent group tag copied to KOT lines. |
| KOT | Kitchen Order Ticket snapshot for FOOD or DRINKS station routing. |
| BOT | Bar ticket; technically a `KOT` row with `ticket_type=bar`. |
| Ticket Print Status | `PENDING`, `PRINTED`, or `CANCELLED`; independent from KOT lifecycle status. |
| Receipt Print | `Order.invoice_printed*` written by `settle_order()`; the actual print runs non-blockingly after settlement. |
| Settlement | `orders.services.settle_order()`, which validates payment/stock and submits an order atomically. |
| Return | Negative draft order linked to an original submitted paid order; `submit_return()` restores stock and mirrors refund rows. |
| Discard | Retained `DISCARDED` state for an empty untouched draft; legacy seed data only. |
| Audit Event | Append-only `OrderAuditEvent` describing an order mutation or lifecycle event. |
| POS History | `services.order_history_rows()` query and its cashier-facing filtered display. |
| Full History | Restaurant-controlled access to returns, cancelled, discarded, and all status filters. |

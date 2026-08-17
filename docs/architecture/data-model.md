# Data Model

## Major Entity Diagram

```mermaid
erDiagram
    CUSTOM_USER ||--o{ POS_OPENING_ENTRY : opens
    CUSTOM_USER ||--o{ ORDER : settles
    RESTAURANT }o--|| MENU : active_menu
    RESTAURANT }o--|| WAREHOUSE : bar_warehouse
    RESTAURANT }o--|| WAREHOUSE : store_warehouse
    PRODUCTION_UNIT }o--|| WAREHOUSE : uses
    MENU ||--o{ MENU_ITEM : contains
    ITEM ||--o{ MENU_ITEM : priced_as
    ITEM_GROUP ||--o{ ITEM : classifies
    UOM ||--o{ ITEM : measures
    ITEM ||--o{ ITEM_ADD_ON : parent
    ITEM ||--o{ ITEM_ADD_ON : add_on
    POS_OPENING_ENTRY ||--o{ ORDER : owns
    POS_OPENING_ENTRY ||--o{ OPENING_PAYMENT : declares
    POS_OPENING_ENTRY ||--o| POS_CLOSING_ENTRY : closes
    POS_CLOSING_ENTRY ||--o{ CLOSING_PAYMENT : counts
    MODE_OF_PAYMENT ||--o| PAYMENT_GL_MAPPING : maps
    MODE_OF_PAYMENT ||--o{ ORDER_PAYMENT : labels
    ORDER ||--o{ ORDER_ITEM : contains
    ORDER ||--o{ ORDER_PAYMENT : receives
    ORDER ||--o{ KOT : generates
    ORDER ||--o{ ORDER_AUDIT_EVENT : records
    ITEM ||--o{ BIN : stocked_in
    WAREHOUSE ||--o{ BIN : contains
    ITEM ||--o{ STOCK_LEDGER_ENTRY : moves
    WAREHOUSE ||--o{ STOCK_LEDGER_ENTRY : moves
    STOCK_ENTRY ||--o{ STOCK_ENTRY_DETAIL : lines
    STOCK_RECONCILIATION ||--o{ STOCK_RECONCILIATION_ITEM : lines
    PURCHASE_RECEIPT ||--o{ PURCHASE_RECEIPT_ITEM : lines
```

## Shared Conventions

Most project domain models extend `apps.utils.models.BaseModel`, adding `created_at` and `updated_at`; `users.CustomUser` instead extends Django's `AbstractUser`. Money and quantities use `DecimalField`; no money uses `FloatField`. Foreign keys for historical business documents generally use `PROTECT` or `SET_NULL`. Child rows of draft documents use `CASCADE` where deleting the parent is still allowed.

## Settings and Routing

- `Restaurant`: singleton enforced by `singleton_key` and `clean()`. `load()` returns the first row with active menu and warehouse relations loaded.
- `ProductionUnit`: one row per department via a unique constraint. Stores station warehouse, takeaway-ticket suppression, and printer metadata.
- Warehouse role is inferred from references, not a warehouse type field.

## Product and Menu Entities

- `ItemGroup`: flat category.
- `UOM`: stock unit.
- `Item`: item master with independent `is_sales_item`, `is_stock_item`, and `is_purchase_item` flags. `has_variants=True` makes it a non-sellable/non-purchasable template in `Item.save()`.
- `Menu`: named enabled collection.
- `MenuItem`: priced item on a menu, unique per menu/item, with denormalized name and special/disabled flags.
- `ItemAddOn`: parent/add-on relationship; the add-on price is resolved from the active menu, not stored here.
- `ItemVariant`: parent/variant relationship. It is modeled, but no current POS variant selector uses it.

## Stock Entities

- `Bin`: current actual quantity, reserved quantity, valuation rate, and stock value for one item/warehouse pair.
- `StockLedgerEntry`: signed movement with running quantity and serialized FIFO queue. The voucher type/number/detail fields link it back to source documents.
- `StockEntry` and `StockEntryDetail`: receipt or Store-to-Kitchen/Bar transfer.
- `StockReconciliation` and `StockReconciliationItem`: counted quantity adjustment with reason and warehouse.
- `PurchaseReceipt` and `PurchaseReceiptItem`: supplier goods into the central Store.

## Order Entities

- `Order`: one operational sale/return document. It owns totals, status, shift, cashier, receipt-printed state, warehouse snapshot, return linkage, and audit history.
- `OrderItem`: line snapshot with item name, rate, amount, department, stock flag, menu line, comments, customer index, and optional return source.
- `OrderPayment`: payment line inside an order. Positive on sales; negative refund rows only on return orders. It is protected from edits after the order is submitted or ticketed.
- `KOT`/`KOTItem`: immutable order-to-station snapshots; KOT print status is mutable for dispatch/retry.
- `OrderAuditEvent`: append-only event row. It uses `PROTECT` from the order and refuses update/delete.
- `OrderSequence`: locked counter used for human-facing order numbers.

## Shift and Payment Entities

- `POSOpeningEntry`: global shift parent. Open means `SUBMITTED` with no closing link; closed means `SUBMITTED` with a closing link.
- `OpeningPayment`: mode-specific opening balance.
- `POSClosingEntry`: one-to-one reconciliation document linked to the opening.
- `ClosingPayment`: counted, expected, and difference values per opening mode.
- `ModeOfPayment`: enabled payment master with one conditional default.
- `PaymentGLMapping`: one-to-one mode-to-account-name mapping.

## Important Constraints and Methods

- `Order` constrains guest count, cancellation reason, and unique human order number.
- `OrderItem` constrains positive normal quantity, non-negative rate, and customer index; return lines are negative and linked to source lines.
- `Order.save()`, `OrderItem.save/delete()`, `OrderPayment.save/delete()`, KOT saves, and audit-event saves enforce historical protections.
- Inventory document saves reject most post-submit mutations, but service functions remain required because direct status changes can bypass posting.
- `StockLedgerEntry` has no model-level save/delete immutability guard; `editable=False` does not protect direct ORM writes.

## Migration History Signals

The current schema is the result of substantial cleanup migrations, not the older plan vocabulary. Important current-history markers include:

- `settings/0017_single_location_data.py` and `0018_remove_restaurant_branch_remove_posprofile_branch_and_more.py`: move toward the single Restaurant configuration and remove Branch/POSProfile structures.
- `settings/0023_restaurant_singleton_key_and_more.py` and `0024_restaurant_store_warehouse_and_more.py`: enforce the singleton key and central Store warehouse semantics.
- `inventory/0014_hardcode_fifo.py`, `0015_simplify_stock_entry.py`, and `0019_item_sales_purchase_flags.py`: establish current FIFO and independent item flags.
- `inventory/0022_stockreconciliation_reason_and_more.py` through `0025_alter_item_image.py`: required reconciliation reasons and current item image default.
- `menu/0006_remove_pricelist_menu_delete_itemprice_and_more.py`: remove legacy PriceList/ItemPrice models.
- `payments/0003_alter_paymentglmapping_options_and_more.py` and `0004_modeofpayment_payments_one_default_mode.py`: current one-to-one GL mapping and one-default invariant.

When a model appears to conflict with `FEATURES.md` or `docs/archive/PLAN-history.md`,
inspect the latest model and migrations first. The archive contains deferred or removed
concepts and is not the live schema.

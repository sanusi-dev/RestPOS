# Products and Menu Workflow

## Item Master

`inventory.Item` is the shared product/material record. Its sales, stock, and purchase flags are independent. `department` is `FOOD` or `DRINKS`; department drives ticket routing and the DRINKS-only POS stock policy, not whether an item is inherently stock-tracked.

`Item.save()` generates an `ITEM-####` code under a lock, makes variant templates non-sellable/non-stock/purchase, and removes add-on rows when an item becomes non-sellable. `Item.clean()` prevents templates from being stock/sales/purchase items, validates variant parents, and blocks turning off sales while an enabled menu line exists.

## Menu Resolution

`Restaurant.active_menu` identifies the menu used by POS. `_build_order_context()` requires the menu to be enabled and filters its `MenuItem` rows to `disabled=False`. Search checks menu line name, item name, and item code. Categories come from `ItemGroup`; special filter checks `MenuItem.special_dish`.

`MenuItem.rate` is the selling rate. `MenuItem.clean()` requires a sellable, enabled, non-template Item. Its denormalized `item_name` fills only when blank, so later Item renames do not automatically update menu lines.

## Add-ons

`ItemAddOn` connects a parent item to an add-on item. The model requires the add-on to be active, sellable, non-template, and present on a menu. The POS dialog loads only add-ons with an enabled active-menu price. `apply_add_on_line()` validates the selected IDs, adds parent and add-ons as separate `OrderItem` rows, applies each active-menu rate, and recalculates totals.

## Variants

`ItemVariant` links a parent item to a variant item and requires the variant on at least one menu. The seed command puts variant items directly on the menu and omits the template line. The current POS has no variant selection endpoint or dialog; a parent selection workflow is not implemented.

## Backoffice

The Menu backoffice groups menu setup into a dashboard, menu register, menu-line register, add-on register, and variant register. The dashboard and menu register identify the configured enabled `Restaurant.active_menu` as **Live on POS**; activation remains controlled from Restaurant settings. Menu-line screens show the source inventory code, group, department, customer-facing rate, and availability state.

The add-on register resolves each relationship against the enabled active menu and displays its effective `MenuItem.rate`, or an explicit unpriced state when no enabled active-menu line exists. The add-on editor explains that the relationship controls availability while the menu line owns the price. `apps/menu/views.py` provides direct login-protected CRUD for menus, menu lines, add-ons, and variant relationships. `Menu` and `MenuItem` have no service layer. Delete endpoints exist for menu lines, add-ons, and variants; there is no menu delete endpoint.

## Setup Commands

- `seed_menu_catalog` atomically seeds Nigerian restaurant raw/finished items, variant families, menu lines, add-ons, and the active menu.
- `seed_pos_setup` creates Restaurant, Bar/Kitchen/Store warehouses, payment modes/mappings, production units, and invokes menu seeding when no active menu exists.
- `InventoryConfig.ready()` seeds baseline UOMs and item groups after migrations.

## Catalog Failure Cases

- No Restaurant or no enabled active menu renders a setup error.
- Disabled menu lines are hidden.
- A drink without `is_stock_item`, a missing/disabled Bar warehouse, or no available unreserved quantity is shown disabled with a setup/out-of-stock message.
- The catalog query does not independently filter `Item.disabled` or `Item.is_sales_item`; the add POST rejects those states server-side.

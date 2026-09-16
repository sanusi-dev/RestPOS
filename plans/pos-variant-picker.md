# POS Variant Picker — Implementation Plan

**Status:** proposed (awaiting developer review; not yet in `PLAN.md` / `FEATURES.md`).
**Scope:** one picker dialog on the POS. No schema change. Back-office variant CRUD unchanged.

## 1. Objective

Tapping a grouped dish (e.g. Chicken) opens a single-choice variant dialog
(Quarter / Half / Full) with per-size price and stock state. Confirming adds exactly one
variant line to the active customer card. Flat variant cards remain valid and keep working;
the picker is a catalog-density and mis-tap improvement, not a new sales path.

This is not the add-on flow: add-ons are multi-select checkboxes; variants are single-choice
radio. One line, one size, always.

## 2. No model changes

- Grouping source is `menu.ItemVariant(parent_item → variant_item)` (`apps/menu/models.py:115-130`).
- Sellability gate stays `menu.MenuItem.clean()` (`models.py:47-57`): template items
  (`inventory.Item.has_variants=True`) can never be menu lines; each variant must hold its
  own enabled `MenuItem` on the active menu with its own `rate`.
- `inventory.Item.variant_of` / `has_variants` (`apps/inventory/models.py:111-118`) continue
  to enforce template-is-unsellable at the item level. The picker does not read
  `variant_of` for grouping; `ItemVariant` is the POS grouping authority. If a variant item
  lacks an `ItemVariant` row it stays a flat card (current behaviour).

## 3. Catalog grouping

`apps/orders/views_pos.py:_build_order_context` (`:181-256`):

- Prefetch `item__pos_variants__variant_item__menu_items` alongside the existing
  `item__add_ons` prefetch (`:196-197`).
- Build `variant_groups`: for each `MenuItem` on the active menu whose item is the
  `variant_item` of one or more `ItemVariant` rows, attach it to its parent(s). A variant
  with two parents appears under both (matches back-office allowing it).
- Emit `catalog_cards`: one entry per parent-with-variants plus one per ungrouped
  `MenuItem`. Parent card display: parent `item_name`, parent image (fallback initials, same
  as today), parent item group name, price label `₦min – ₦max` across its enabled,
  on-menu variants.
- `drink_stock_available` (`services.py:695-728`) keeps running per variant `MenuItem`.
  Parent card `stock_unavailable` = all its variants unavailable; tooltip lists why
  (out of stock / setup). Dialog still shows per-variant state.

`templates/pos/partials/catalog/grid.html:4`:

- Branch on card type. Ungrouped cards keep the exact current behaviour (direct
  `hx-post pos_order_add_item` when no add-ons, `hx-get pos_order_add_on_dialog` when
  add-ons exist).
- Parent cards always `hx-get pos_order_variant_dialog` with the parent `item_id`
  (unless `order_sent` or all-variants-unavailable, which disables like today).
- Search / group / specials filtering matches parent name, variant names, and item code;
  a query matching any variant surfaces the parent card.

## 4. Variant dialog (new, mirrors add-on dialog)

New `GET order/<pk>/variant-dialog/<parent_item_id>/` → `pos_order_variant_dialog`,
patterned on `pos_order_add_on_dialog` (`views_pos.py:549-585`):

- Resolves active menu; 404 when none (same as add-ons).
- Loads parent `Item`; collects `ItemVariant` rows for the parent whose `variant_item`
  is sellable, enabled, and holds an enabled `MenuItem` on the active menu. Order by
  variant `rate`, then name. Empty list → 404 (card should not have rendered).
- Renders `templates/pos/partials/catalog/variant_dialog.html`, visually mirroring
  `add_on_dialog.html:1-53` (same Alpine `posModalDialog`, header with parent name,
  footer Cancel / Add to order, `HX-Trigger: close-add-on-dialog` on success).
- Body: radio group `variant_item_id` (one per variant) showing variant name, `₦rate`,
  and per-variant stock state (drinks: Out of stock radio disabled with message; food:
  always selectable). First available variant preselected. Below: qty stepper
  (default 1, same bounds as `pos_order_add_item`) and optional comments textarea
  (maxlength 200, same rule as `:660-662`).
- Out of scope v1: combining variant choice and add-on checkboxes in one dialog. If the
  chosen variant itself has add-ons, submit chains into the existing add-on dialog for
  that variant item (two-step: variant → add-ons → cart). Items with variants but no
  add-ons complete in one step.

## 5. Submit path (reuse, tighten validation)

`POST order/<pk>/add-item/` (`views_pos.py:627-687`) gains optional `variant_item_id`:

- No `variant_item_id` → current behaviour unchanged (flat card or add-on submit).
- With `variant_item_id`: `item_id` must be a parent holding an `ItemVariant` row for that
  variant; the variant item must be sellable, enabled, and on the active menu. Rate is
  resolved server-side from the variant's `MenuItem.rate` — never from the client — via
  the existing `apply_add_on_line` pricing path (`services.py:824-872`).
- Reject: posting the template/parent itself as the line (`Item.has_variants` → error
  "Choose a size."); variant of another parent; disabled/off-menu variant; `qty <= 0`;
  comments > 200; `add_on_ids` not belonging to the chosen variant (when chained).
- Stock: `add_order_line` (`services.py:324-361`) reserves the variant item's bin
  (`reserve_drink_stock` on `drink_quantities`), so drink sizes deduct the correct SKU.
  Food variants behave as today (no reservation/deduction).
- Post-send lock unchanged (`:642-643`, `models._ensure_editable`): dialog and submit both
  refuse once tickets exist.
- Audit: `ITEM_ADDED` metadata gains `parent_item_id` alongside `item_id`/qty/card, so
  per-size analytics stay exact while parent affinity is recoverable.

Line merging is unchanged: same variant + same card + same comments merges qty, per
`add_order_line:344-349`.

## 6. Cart, tickets, receipts, returns — no change

- `OrderItem` keeps one `item` (the variant), one `rate`, one `menu_item`. Tickets group by
  department/customer as today; receipts print the variant `item_name` at its rate.
- Returns mirror variant lines exactly like flat lines (`make_return`/`submit_return`
  unchanged). Recipe cards attach to variant items (already the §4.12 rule); theoretical
  usage explodes per variant sold.

## 7. Tests

`apps/orders/tests/test_pos_variants.py` (new):

- Catalog groups variants under one parent card with `₦min – ₦max`; ungrouped items render
  flat; search by variant name surfaces the parent.
- Dialog lists only enabled, on-menu variants ordered by rate; out-of-stock drink variant
  renders disabled; food variants always selectable.
- Submit adds the chosen variant at its menu rate with the active `customer_index`;
  template-as-line rejected; cross-parent variant rejected; off-menu/disabled rejected.
- Drink variant reserves and deducts the correct variant bin (two sizes of one parent hold
  independent bins); food variant reserves nothing.
- Variant with add-ons chains to the add-on dialog; add-ons of another item rejected.
- Post-send dialog and submit refused; audit row carries parent + variant.

Existing `test_pos_views.py` and catalog tests stay green (flat cards untouched).

## 8. Rollout and docs (same task, per repo rules)

- No migration, no seed change. Existing menus render grouped automatically wherever
  `ItemVariant` rows exist; dishes without rows are untouched.
- Remove the `FEATURES.md` A2 #9 caveat ("POS variant selection is not yet implemented")
  and describe the picker in one line. Retire this file into `PLAN.md` §4 (planned,
  decision-only) on approval.
- Update `docs/workflows/pos.md` (catalog → picker → cart) and
  `docs/execution-flows/add-to-cart.md` (variant dialog trigger, submit params).

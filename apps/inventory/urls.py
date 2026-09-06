from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", view=views.inventory_dashboard, name="dashboard"),
    path("uoms/", view=views.uom_list, name="uom_list"),
    path("uoms/create/", view=views.uom_create, name="uom_create"),
    path("uoms/<int:pk>/edit/", view=views.uom_update, name="uom_update"),
    path("item-groups/", view=views.item_group_list, name="item_group_list"),
    path("item-groups/create/", view=views.item_group_create, name="item_group_create"),
    path("item-groups/<int:pk>/", view=views.item_group_detail, name="item_group_detail"),
    path("item-groups/<int:pk>/edit/", view=views.item_group_update, name="item_group_update"),
    path("warehouses/", view=views.warehouse_list, name="warehouse_list"),
    path("warehouses/create/", view=views.warehouse_create, name="warehouse_create"),
    path("warehouses/<int:pk>/", view=views.warehouse_detail, name="warehouse_detail"),
    path("warehouses/<int:pk>/edit/", view=views.warehouse_update, name="warehouse_update"),
    path("items/", view=views.item_list, name="item_list"),
    path("items/create/", view=views.item_create, name="item_create"),
    path("items/uom/add/", view=views.item_uom_add, name="item_uom_add"),
    path("items/uom/remove/<int:index>/", view=views.item_uom_remove, name="item_uom_remove"),
    path("items/<int:pk>/", view=views.item_detail, name="item_detail"),
    path("items/<int:pk>/edit/", view=views.item_update, name="item_update"),
    path("stock-entries/", view=views.stock_entry_list, name="stock_entry_list"),
    path("stock-entries/create/", view=views.stock_entry_create, name="stock_entry_create"),
    path("stock-entries/item/add/", view=views.stock_entry_item_add, name="stock_entry_item_add"),
    path("stock-entries/item/remove/<int:index>/", view=views.stock_entry_item_remove, name="stock_entry_item_remove"),
    path("stock-entries/<int:pk>/", view=views.stock_entry_detail, name="stock_entry_detail"),
    path("stock-entries/<int:pk>/submit/", view=views.stock_entry_submit, name="stock_entry_submit"),
    path("stock-entries/<int:pk>/cancel/", view=views.stock_entry_cancel, name="stock_entry_cancel"),
    path("reconciliations/", view=views.reconciliation_list, name="reconciliation_list"),
    path("reconciliations/create/", view=views.reconciliation_create, name="reconciliation_create"),
    path("reconciliations/item/add/", view=views.reconciliation_item_add, name="reconciliation_item_add"),
    path(
        "reconciliations/item/remove/<int:index>/",
        view=views.reconciliation_item_remove,
        name="reconciliation_item_remove",
    ),
    path("reconciliations/<int:pk>/", view=views.reconciliation_detail, name="reconciliation_detail"),
    path(
        "reconciliations/<int:pk>/submit/",
        view=views.reconciliation_submit,
        name="reconciliation_submit",
    ),
    path(
        "reconciliations/<int:pk>/cancel/",
        view=views.reconciliation_cancel,
        name="reconciliation_cancel",
    ),
    path("purchase-receipts/", view=views.purchase_receipt_list, name="purchase_receipt_list"),
    path(
        "purchase-receipts/create/",
        view=views.purchase_receipt_create,
        name="purchase_receipt_create",
    ),
    path(
        "purchase-receipts/item/add/",
        view=views.purchase_receipt_item_add,
        name="purchase_receipt_item_add",
    ),
    path(
        "purchase-receipts/item/remove/<int:index>/",
        view=views.purchase_receipt_item_remove,
        name="purchase_receipt_item_remove",
    ),
    path(
        "purchase-receipts/item/meta/",
        view=views.purchase_receipt_item_meta,
        name="purchase_receipt_item_meta",
    ),
    path(
        "purchase-receipts/item/stock-qty/",
        view=views.purchase_receipt_stock_qty_preview,
        name="purchase_receipt_stock_qty_preview",
    ),
    path(
        "purchase-receipts/<int:pk>/",
        view=views.purchase_receipt_detail,
        name="purchase_receipt_detail",
    ),
    path(
        "purchase-receipts/<int:pk>/submit/",
        view=views.purchase_receipt_submit,
        name="purchase_receipt_submit",
    ),
    path(
        "purchase-receipts/<int:pk>/cancel/",
        view=views.purchase_receipt_cancel,
        name="purchase_receipt_cancel",
    ),
    path("stock-ledger/", view=views.stock_ledger_list, name="stock_ledger_list"),
    path("stock-balance/", view=views.stock_balance_list, name="stock_balance_list"),
]

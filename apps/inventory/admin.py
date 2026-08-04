from django.contrib import admin

from .models import (
    UOM,
    Bin,
    Item,
    ItemGroup,
    PurchaseReceipt,
    PurchaseReceiptItem,
    StockEntry,
    StockEntryDetail,
    StockLedgerEntry,
    StockReconciliation,
    StockReconciliationItem,
    Warehouse,
)


@admin.register(UOM)
class UOMAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(ItemGroup)
class ItemGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name", "description")
    ordering = ("name",)


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "disabled", "created_at")
    list_filter = ("disabled",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        "item_code",
        "item_name",
        "item_group",
        "stock_uom",
        "department",
        "is_stock_item",
        "disabled",
    )
    list_filter = ("department", "is_stock_item", "disabled", "item_group")
    list_select_related = ("item_group", "stock_uom")
    search_fields = ("item_code", "item_name", "description")
    ordering = ("item_name",)
    inlines = []


@admin.register(Bin)
class BinAdmin(admin.ModelAdmin):
    list_display = ("item", "warehouse", "actual_qty", "reserved_qty", "valuation_rate", "stock_value")
    list_filter = ("warehouse",)
    list_select_related = ("item", "warehouse")
    search_fields = ("item__item_name", "item__item_code", "warehouse__name")


@admin.register(StockLedgerEntry)
class StockLedgerEntryAdmin(admin.ModelAdmin):
    list_display = (
        "posting_datetime",
        "item",
        "warehouse",
        "actual_qty",
        "qty_after_transaction",
        "valuation_rate",
        "voucher_type",
        "voucher_no",
        "is_cancelled",
    )
    list_filter = ("voucher_type", "is_cancelled", "warehouse", "item")
    list_select_related = ("item", "warehouse")
    search_fields = ("item__item_name", "item__item_code", "voucher_no", "warehouse__name")
    ordering = ("-posting_datetime",)

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False


class StockEntryDetailInline(admin.TabularInline):
    model = StockEntryDetail
    extra = 1
    exclude = ("source_warehouse", "target_warehouse")


@admin.register(StockEntry)
class StockEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "purpose", "posting_date", "status")
    list_filter = ("purpose", "status")
    search_fields = ("remarks",)
    ordering = ("-posting_date", "-created_at")
    inlines = [StockEntryDetailInline]


class StockReconciliationItemInline(admin.TabularInline):
    model = StockReconciliationItem
    extra = 1
    readonly_fields = ("current_qty",)


@admin.register(StockReconciliation)
class StockReconciliationAdmin(admin.ModelAdmin):
    list_display = ("id", "purpose", "reason", "posting_date", "warehouse", "status")
    list_filter = ("purpose", "reason", "status", "posting_date")
    list_select_related = ("warehouse",)
    search_fields = ("remarks", "warehouse__name")
    ordering = ("-posting_date", "-created_at")
    inlines = [StockReconciliationItemInline]


class PurchaseReceiptItemInline(admin.TabularInline):
    model = PurchaseReceiptItem
    extra = 1
    readonly_fields = ("amount",)


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(admin.ModelAdmin):
    list_display = ("supplier_name", "posting_date", "status", "warehouse", "total")
    list_filter = ("status", "posting_date", "warehouse")
    list_select_related = ("warehouse",)
    search_fields = ("supplier_name", "supplier_delivery_note")
    ordering = ("-posting_date", "-created_at")
    inlines = [PurchaseReceiptItemInline]
    readonly_fields = ("total",)

    def get_readonly_fields(self, request, obj=None):
        return (*self.readonly_fields, "warehouse")

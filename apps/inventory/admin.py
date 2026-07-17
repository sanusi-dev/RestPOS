from django.contrib import admin

from .models import (
    UOM,
    Batch,
    Bin,
    Item,
    ItemBarcode,
    ItemGroup,
    ItemUOMConversion,
    ProductBundle,
    ProductBundleItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    ReorderLevel,
    StockEntry,
    StockEntryDetail,
    StockLedgerEntry,
    StockReconciliation,
    StockReconciliationItem,
    Warehouse,
)


@admin.register(UOM)
class UOMAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(ItemGroup)
class ItemGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "is_group", "created_at")
    list_filter = ("is_group",)
    search_fields = ("name", "description")
    ordering = ("name",)


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "parent", "is_group", "is_rejected", "disabled")
    list_filter = ("branch", "is_group", "is_rejected", "disabled")
    search_fields = ("name", "branch__name")
    ordering = ("branch__name", "name")


class ItemBarcodeInline(admin.TabularInline):
    model = ItemBarcode
    extra = 1


class ItemUOMConversionInline(admin.TabularInline):
    model = ItemUOMConversion
    extra = 1


class ReorderLevelInline(admin.TabularInline):
    model = ReorderLevel
    extra = 1


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
    list_filter = ("department", "is_stock_item", "disabled", "item_group", "valuation_method")
    search_fields = ("item_code", "item_name", "description")
    ordering = ("item_name",)
    inlines = [ItemBarcodeInline, ItemUOMConversionInline, ReorderLevelInline]


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("batch_id", "item", "expiry_date", "manufacturing_date", "batch_qty")
    list_filter = ("item",)
    search_fields = ("batch_id", "item__item_name", "item__item_code")
    readonly_fields = ("batch_qty",)
    ordering = ("-created_at",)


class ProductBundleItemInline(admin.TabularInline):
    model = ProductBundleItem
    extra = 1


@admin.register(ProductBundle)
class ProductBundleAdmin(admin.ModelAdmin):
    list_display = ("parent_item", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("parent_item__item_name", "parent_item__item_code")
    inlines = [ProductBundleItemInline]


@admin.register(Bin)
class BinAdmin(admin.ModelAdmin):
    list_display = ("item", "warehouse", "actual_qty", "reserved_qty", "valuation_rate", "stock_value")
    list_filter = ("warehouse",)
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
    search_fields = ("item__item_name", "item__item_code", "voucher_no", "warehouse__name")
    ordering = ("-posting_datetime",)

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False


class StockEntryDetailInline(admin.TabularInline):
    model = StockEntryDetail
    extra = 1


@admin.register(StockEntry)
class StockEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "purpose", "posting_date", "from_warehouse", "to_warehouse", "status")
    list_filter = ("purpose", "status", "posting_date")
    search_fields = ("remarks", "from_warehouse__name", "to_warehouse__name")
    ordering = ("-posting_date", "-created_at")
    inlines = [StockEntryDetailInline]


class StockReconciliationItemInline(admin.TabularInline):
    model = StockReconciliationItem
    extra = 1
    readonly_fields = ("current_qty",)


@admin.register(StockReconciliation)
class StockReconciliationAdmin(admin.ModelAdmin):
    list_display = ("id", "purpose", "posting_date", "warehouse", "status")
    list_filter = ("purpose", "status", "posting_date")
    search_fields = ("remarks", "warehouse__name")
    ordering = ("-posting_date", "-created_at")
    inlines = [StockReconciliationItemInline]


class PurchaseReceiptItemInline(admin.TabularInline):
    model = PurchaseReceiptItem
    extra = 1
    readonly_fields = ("accepted_qty", "amount")


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(admin.ModelAdmin):
    list_display = ("supplier_name", "posting_date", "status", "accepted_warehouse", "total")
    list_filter = ("status", "posting_date", "accepted_warehouse")
    search_fields = ("supplier_name", "supplier_delivery_note")
    ordering = ("-posting_date", "-created_at")
    inlines = [PurchaseReceiptItemInline]
    readonly_fields = ("total",)

from django.contrib import admin

from .models import (
    UOM,
    Bin,
    Item,
    ItemGroup,
    ItemUOMConversion,
    PurchaseReceipt,
    PurchaseReceiptItem,
    StockEntry,
    StockEntryDetail,
    StockLedgerEntry,
    StockReconciliation,
    StockReconciliationItem,
    Warehouse,
)


class SubmittedDocumentAdminMixin:
    """Lock submitted/cancelled inventory documents in Django admin."""

    IMMUTABLE_STATUSES = frozenset({"SUBMITTED", "CANCELLED"})

    def _is_immutable(self, obj):
        return obj is not None and getattr(obj, "status", None) in self.IMMUTABLE_STATUSES

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if self._is_immutable(obj):
            return [field.name for field in self.model._meta.fields]
        return readonly

    def has_delete_permission(self, request, obj=None):
        if self._is_immutable(obj):
            return False
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if self._is_immutable(obj):
            return False
        return super().has_change_permission(request, obj)


class SubmittedInlineMixin:
    """Make inlines read-only when the parent document is submitted or cancelled."""

    def has_add_permission(self, request, obj=None):
        if obj is not None and getattr(obj, "status", None) in SubmittedDocumentAdminMixin.IMMUTABLE_STATUSES:
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj is not None and getattr(obj, "status", None) in SubmittedDocumentAdminMixin.IMMUTABLE_STATUSES:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and getattr(obj, "status", None) in SubmittedDocumentAdminMixin.IMMUTABLE_STATUSES:
            return False
        return super().has_delete_permission(request, obj)


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


class ItemUOMConversionInline(admin.TabularInline):
    model = ItemUOMConversion
    extra = 0


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
    inlines = [ItemUOMConversionInline]


@admin.register(Bin)
class BinAdmin(admin.ModelAdmin):
    list_display = ("item", "warehouse", "actual_qty", "reserved_qty", "valuation_rate", "display_stock_value")
    list_filter = ("warehouse",)
    list_select_related = ("item", "warehouse")
    search_fields = ("item__item_name", "item__item_code", "warehouse__name")

    @admin.display(description="Stock value")
    def display_stock_value(self, obj):
        return obj.stock_value


@admin.register(StockLedgerEntry)
class StockLedgerEntryAdmin(admin.ModelAdmin):
    list_display = (
        "posting_datetime",
        "posting_date",
        "item",
        "warehouse",
        "quantity",
        "unit_rate",
        "stock_value_change",
        "variance_type",
        "variance_amount",
        "voucher_type",
        "voucher_no",
        "reversal_of_sle",
    )
    list_filter = ("voucher_type", "variance_type", "warehouse", "item")
    list_select_related = ("item", "warehouse", "reversal_of_sle")
    search_fields = ("item__item_name", "item__item_code", "voucher_no", "warehouse__name")
    ordering = ("-posting_datetime",)

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class StockEntryDetailInline(SubmittedInlineMixin, admin.TabularInline):
    model = StockEntryDetail
    extra = 1
    exclude = ("source_warehouse", "target_warehouse")


@admin.register(StockEntry)
class StockEntryAdmin(SubmittedDocumentAdminMixin, admin.ModelAdmin):
    list_display = ("id", "purpose", "posting_date", "status", "mode_of_payment")
    list_filter = ("purpose", "status")
    search_fields = ("remarks",)
    ordering = ("-posting_date", "-created_at")
    inlines = [StockEntryDetailInline]


class StockReconciliationItemInline(SubmittedInlineMixin, admin.TabularInline):
    model = StockReconciliationItem
    extra = 1
    readonly_fields = ("current_qty",)


@admin.register(StockReconciliation)
class StockReconciliationAdmin(SubmittedDocumentAdminMixin, admin.ModelAdmin):
    list_display = ("id", "purpose", "reason", "posting_date", "warehouse", "status")
    list_filter = ("purpose", "reason", "status", "posting_date")
    list_select_related = ("warehouse",)
    search_fields = ("remarks", "warehouse__name")
    ordering = ("-posting_date", "-created_at")
    inlines = [StockReconciliationItemInline]


class PurchaseReceiptItemInline(SubmittedInlineMixin, admin.TabularInline):
    model = PurchaseReceiptItem
    extra = 1
    readonly_fields = ("amount", "conversion_factor")


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(SubmittedDocumentAdminMixin, admin.ModelAdmin):
    list_display = ("supplier_name", "posting_date", "status", "warehouse", "total")
    list_filter = ("status", "posting_date", "warehouse")
    list_select_related = ("warehouse",)
    search_fields = ("supplier_name", "supplier_delivery_note")
    ordering = ("-posting_date", "-created_at")
    inlines = [PurchaseReceiptItemInline]
    readonly_fields = ("total",)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if "warehouse" not in readonly:
            readonly.append("warehouse")
        if "total" not in readonly:
            readonly.append("total")
        return readonly

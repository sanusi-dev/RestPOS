from django.contrib import admin

from .models import KOT, KOTItem, Order, OrderItem, OrderPayment


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ("item", "qty", "rate", "amount", "customer_index")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class OrderPaymentInline(admin.TabularInline):
    model = OrderPayment
    extra = 0
    readonly_fields = ("mode_of_payment", "amount", "reference_no", "created_at", "updated_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "order_type", "customer_name", "status", "grand_total", "posting_date")
    list_filter = ("status", "order_type", "posting_date")
    search_fields = ("invoice_number", "customer_name")
    inlines = (OrderItemInline, OrderPaymentInline)
    ordering = ("-posting_date",)
    readonly_fields = (
        "invoice_number",
        "order_number",
        "order_type",
        "customer_name",
        "guest_count",
        "cashier",
        "status",
        "is_paid",
        "invoice_printed",
        "posting_date",
        "posting_time",
        "net_total",
        "grand_total",
        "rounded_total",
        "paid_amount",
        "change_amount",
        "cancel_reason",
        "cancel_reason_note",
        "cancelled_by",
        "cancelled_at",
        "opening_entry",
        "arrived_time",
        "is_return",
        "return_against",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(KOT)
class KOTAdmin(admin.ModelAdmin):
    list_display = (
        "kot_number",
        "ticket_type",
        "type",
        "print_status",
        "status",
        "production_unit",
        "order",
        "posting_datetime",
    )
    list_filter = ("ticket_type", "type", "print_status", "status", "production_unit")
    search_fields = ("kot_number",)
    ordering = ("-posting_datetime",)
    readonly_fields = (
        "order",
        "production_unit",
        "type",
        "kot_number",
        "ticket_type",
        "status",
        "print_status",
        "created_by",
        "posting_datetime",
        "order_number",
        "original_kots",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(KOTItem)
class KOTItemAdmin(admin.ModelAdmin):
    list_display = ("kot", "item_name", "qty", "cancelled_qty")
    readonly_fields = (
        "kot",
        "item",
        "item_name",
        "qty",
        "cancelled_qty",
        "comments",
        "customer_index",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

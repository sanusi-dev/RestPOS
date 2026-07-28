from django.contrib import admin

from .models import KOT, KOTItem, Order, OrderItem, OrderPayment, OrderTax


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ("item", "qty", "rate", "amount", "customer_index")
    readonly_fields = ("amount",)


class OrderPaymentInline(admin.TabularInline):
    model = OrderPayment
    extra = 0


class OrderTaxInline(admin.TabularInline):
    model = OrderTax
    extra = 0
    fields = ("description", "charge_type", "rate", "tax_amount")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "order_type", "customer_name", "status", "grand_total", "posting_date")
    list_filter = ("status", "order_type", "posting_date", "branch")
    search_fields = ("invoice_number", "customer_name")
    inlines = [OrderItemInline, OrderPaymentInline, OrderTaxInline]
    ordering = ("-posting_date",)


@admin.register(KOT)
class KOTAdmin(admin.ModelAdmin):
    list_display = ("kot_number", "type", "production_unit", "order", "posting_datetime")
    list_filter = ("type", "production_unit")
    search_fields = ("kot_number",)
    ordering = ("-posting_datetime",)


@admin.register(KOTItem)
class KOTItemAdmin(admin.ModelAdmin):
    list_display = ("kot", "item_name", "qty", "cancelled_qty")

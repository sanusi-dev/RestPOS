from django.contrib import admin

from .models import (
    ProductionUnit,
    Restaurant,
)


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ("company", "invoice_series_prefix", "active_menu", "store_warehouse", "default_warehouse")
    list_select_related = ("active_menu", "store_warehouse", "default_warehouse")
    search_fields = ("company",)


@admin.register(ProductionUnit)
class ProductionUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "warehouse", "printer_ip")
    list_filter = ("department",)
    list_select_related = ("warehouse",)
    search_fields = ("name",)
    ordering = ("name",)

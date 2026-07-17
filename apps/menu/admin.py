from django.contrib import admin

from .models import ItemAddOn, ItemPrice, ItemVariant, Menu, MenuItem, PriceList


class MenuItemInline(admin.TabularInline):
    model = MenuItem
    extra = 1
    autocomplete_fields = ["item"]


@admin.register(Menu)
class MenuAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "enabled", "created_at")
    list_filter = ("branch", "enabled")
    search_fields = ("name", "branch__name")
    ordering = ("branch__name", "name")
    inlines = [MenuItemInline]


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("item_name", "menu", "rate", "special_dish", "disabled")
    list_filter = ("menu", "special_dish", "disabled")
    search_fields = ("item_name", "item__item_code", "menu__name")
    ordering = ("item_name",)


class ItemPriceInline(admin.TabularInline):
    model = ItemPrice
    extra = 0
    readonly_fields = ("item", "price_list_rate", "uom")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PriceList)
class PriceListAdmin(admin.ModelAdmin):
    list_display = ("name", "enabled", "selling", "buying", "menu", "created_at")
    list_filter = ("enabled", "selling", "buying")
    search_fields = ("name", "menu__name")
    ordering = ("name",)
    inlines = [ItemPriceInline]


@admin.register(ItemPrice)
class ItemPriceAdmin(admin.ModelAdmin):
    list_display = ("item", "price_list", "price_list_rate", "uom")
    list_filter = ("price_list", "uom")
    search_fields = ("item__item_name", "item__item_code", "price_list__name")
    ordering = ("item__item_name",)


@admin.register(ItemAddOn)
class ItemAddOnAdmin(admin.ModelAdmin):
    list_display = ("parent_item", "add_on_item", "created_at")
    list_filter = ("parent_item",)
    search_fields = ("parent_item__item_name", "add_on_item__item_name")
    ordering = ("parent_item__item_name",)


@admin.register(ItemVariant)
class ItemVariantAdmin(admin.ModelAdmin):
    list_display = ("parent_item", "variant_item", "created_at")
    list_filter = ("parent_item",)
    search_fields = ("parent_item__item_name", "variant_item__item_name")
    ordering = ("parent_item__item_name",)

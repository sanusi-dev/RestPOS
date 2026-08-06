from django.contrib import admin

from .models import ItemAddOn, ItemVariant, Menu, MenuItem


class MenuItemInline(admin.TabularInline):
    model = MenuItem
    extra = 1
    autocomplete_fields = ["item"]


@admin.register(Menu)
class MenuAdmin(admin.ModelAdmin):
    list_display = ("name", "enabled", "created_at")
    list_filter = ("enabled",)
    search_fields = ("name",)
    ordering = ("name",)
    inlines = [MenuItemInline]


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ("item_name", "menu", "rate", "special_dish", "disabled")
    list_filter = ("menu", "special_dish", "disabled")
    list_select_related = ("menu",)
    search_fields = ("item_name", "item__item_code", "menu__name")
    ordering = ("item_name",)


@admin.register(ItemAddOn)
class ItemAddOnAdmin(admin.ModelAdmin):
    list_display = ("parent_item", "add_on_item", "created_at")
    list_filter = ("parent_item",)
    list_select_related = ("parent_item", "add_on_item")
    search_fields = ("parent_item__item_name", "add_on_item__item_name")
    ordering = ("parent_item__item_name",)


@admin.register(ItemVariant)
class ItemVariantAdmin(admin.ModelAdmin):
    list_display = ("parent_item", "variant_item", "created_at")
    list_filter = ("parent_item",)
    list_select_related = ("parent_item", "variant_item")
    search_fields = ("parent_item__item_name", "variant_item__item_name")
    ordering = ("parent_item__item_name",)

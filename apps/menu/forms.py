from django import forms

from apps.inventory.models import Item
from apps.utils.forms import StyledModelForm

from .models import ItemAddOn, ItemVariant, Menu, MenuItem, PriceList


class MenuModelForm(StyledModelForm):
    """Base ModelForm for menu forms."""


class MenuForm(MenuModelForm):
    """Form for Menu."""

    class Meta:
        model = Menu
        fields = ["name", "enabled"]


class MenuItemForm(MenuModelForm):
    class Meta:
        model = MenuItem
        fields = ["item", "item_name", "rate", "special_dish", "disabled"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item_name"].widget = forms.HiddenInput()
        # ERPNext-aligned: sellable, non-template, active only (keep current selection if any).
        qs = Item.objects.filter(is_sales_item=True, has_variants=False, disabled=False).order_by("item_name")
        if self.instance and self.instance.item_id:
            qs = qs | Item.objects.filter(pk=self.instance.item_id)
        self.fields["item"].queryset = qs.distinct().order_by("item_name")


class PriceListForm(MenuModelForm):
    class Meta:
        model = PriceList
        fields = ["name", "enabled", "selling", "buying"]


class ItemAddOnForm(MenuModelForm):
    class Meta:
        model = ItemAddOn
        fields = ["parent_item", "add_on_item"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Parent: sellable leaf items that can carry add-ons on the POS.
        # Add-on: same — only sellable, non-template, active items (must also be on a menu; model.clean).
        sellable = Item.objects.filter(is_sales_item=True, has_variants=False, disabled=False).order_by("item_name")
        parent_qs = sellable
        add_on_qs = sellable
        if self.instance and self.instance.pk:
            if self.instance.parent_item_id:
                parent_qs = (parent_qs | Item.objects.filter(pk=self.instance.parent_item_id)).distinct()
            if self.instance.add_on_item_id:
                add_on_qs = (add_on_qs | Item.objects.filter(pk=self.instance.add_on_item_id)).distinct()
        self.fields["parent_item"].queryset = parent_qs.order_by("item_name")
        self.fields["add_on_item"].queryset = add_on_qs.order_by("item_name")


class ItemVariantForm(MenuModelForm):
    class Meta:
        model = ItemVariant
        fields = ["parent_item", "variant_item"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        items = Item.objects.order_by("item_name")
        self.fields["parent_item"].queryset = items
        self.fields["variant_item"].queryset = items

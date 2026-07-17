from django import forms

from apps.inventory.models import Item

from .models import ItemAddOn, ItemVariant, Menu, MenuItem, PriceList

TAILWIND_INPUT_CLASS = (
    "w-full rounded-md border border-gray-300 px-3 py-2 text-sm "
    "focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
)


class MenuModelForm(forms.ModelForm):
    """Base ModelForm that applies Tailwind CSS classes to all fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not field.widget.attrs.get("class"):
                field.widget.attrs["class"] = TAILWIND_INPUT_CLASS


class MenuForm(MenuModelForm):
    class Meta:
        model = Menu
        fields = ["name", "branch", "enabled"]


class MenuItemForm(MenuModelForm):
    class Meta:
        model = MenuItem
        fields = ["item", "item_name", "rate", "special_dish", "disabled"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item_name"].widget = forms.HiddenInput()
        self.fields["item"].queryset = Item.objects.order_by("item_name")


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
        self.fields["parent_item"].queryset = Item.objects.order_by("item_name")
        self.fields["add_on_item"].queryset = Item.objects.order_by("item_name")


class ItemVariantForm(MenuModelForm):
    class Meta:
        model = ItemVariant
        fields = ["parent_item", "variant_item"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent_item"].queryset = Item.objects.order_by("item_name")
        self.fields["variant_item"].queryset = Item.objects.order_by("item_name")

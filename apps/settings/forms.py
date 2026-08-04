from django import forms

from apps.inventory.models import Warehouse
from apps.menu.models import Menu
from apps.utils.forms import active_choices

from .models import (
    ProductionUnit,
    Restaurant,
)

TAILWIND_INPUT_CLASS = (
    "w-full rounded-xl border border-gray-300 px-4 py-3 text-sm "
    "focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-500/25 "
    "bg-white/50 transition-shadow"
)

TAILWIND_CHECKBOX_CLASS = "rounded border-gray-300 text-orange-500 focus:ring-orange-500/25"


class SettingsModelForm(forms.ModelForm):
    """Base ModelForm that applies Tailwind CSS classes to all fields."""

    TEXT_WIDGETS = (
        forms.TextInput,
        forms.Textarea,
        forms.EmailInput,
        forms.URLInput,
        forms.NumberInput,
        forms.PasswordInput,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput) and not field.widget.attrs.get("class"):
                field.widget.attrs["class"] = TAILWIND_CHECKBOX_CLASS
            elif (
                isinstance(field.widget, self.TEXT_WIDGETS)
                and not field.widget.attrs.get("class")
                or isinstance(field.widget, forms.Select)
                and not field.widget.attrs.get("class")
            ):
                field.widget.attrs["class"] = TAILWIND_INPUT_CLASS
        for _name, field in self.fields.items():
            if isinstance(field, forms.ModelChoiceField):
                field.empty_label = f"Select {field.label.lower()}..."


class RestaurantForm(SettingsModelForm):
    """The single settings record: identity, menu, stock, and POS behaviour."""

    class Meta:
        model = Restaurant
        fields = [
            "company",
            "invoice_series_prefix",
            "address",
            "active_menu",
            "store_warehouse",
            "default_warehouse",
            "max_open_drafts",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["max_open_drafts"].required = False
        self.fields["active_menu"].queryset = active_choices(Menu, self.instance.active_menu_id, enabled=True)
        self.fields["default_warehouse"].queryset = active_choices(
            Warehouse, self.instance.default_warehouse_id, disabled=False
        )
        self.fields["store_warehouse"].queryset = active_choices(
            Warehouse, self.instance.store_warehouse_id, disabled=False
        )


class ProductionUnitForm(SettingsModelForm):
    class Meta:
        model = ProductionUnit
        fields = [
            "name",
            "department",
            "warehouse",
            "block_takeaway_kot",
            "printer_ip",
            "printer_paper_width",
            "printer_cut_mode",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = active_choices(Warehouse, self.instance.warehouse_id, disabled=False)
        self.fields["warehouse"].help_text = "FOOD uses Kitchen; DRINKS uses the Bar / POS sales warehouse."

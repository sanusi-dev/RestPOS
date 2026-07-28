from django import forms

from apps.inventory.models import Warehouse
from apps.menu.models import PriceList
from apps.payments.models import ModeOfPayment
from apps.users.models import CustomUser
from apps.utils.forms import active_choices

from .models import (
    Branch,
    POSProfile,
    POSProfilePayment,
    ProductionUnit,
    Restaurant,
    Room,
    Table,
    TaxRate,
    TaxTemplate,
    UserRoomAssignment,
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


class BranchForm(SettingsModelForm):
    class Meta:
        model = Branch
        fields = ["name"]


class RoomForm(SettingsModelForm):
    """Form for Room. Branch is auto-assigned on save."""

    class Meta:
        model = Room
        fields = ["name"]


class TableForm(SettingsModelForm):
    """Form for Table. Branch is derived from room on save."""

    class Meta:
        model = Table
        fields = [
            "room",
            "name",
            "no_of_seats",
            "minimum_seating",
            "table_shape",
            "is_take_away",
            "layout_x",
            "layout_y",
            "layout_width",
            "layout_height",
        ]


class RestaurantForm(SettingsModelForm):
    """Form for Restaurant. Branch is auto-assigned on save."""

    class Meta:
        model = Restaurant
        fields = ["company", "invoice_series_prefix", "address", "default_room", "default_tax_template"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_tax_template"].queryset = active_choices(
            TaxTemplate, self.instance.default_tax_template_id, disabled=False
        )


class UserRoomAssignmentForm(SettingsModelForm):
    """Form for UserRoomAssignment. Branch is derived from room on save."""

    class Meta:
        model = UserRoomAssignment
        fields = ["user", "room"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = CustomUser.objects.order_by("username")


class TaxTemplateForm(SettingsModelForm):
    """Form for TaxTemplate. Company defaults from Restaurant.company."""

    class Meta:
        model = TaxTemplate
        fields = ["title", "is_default", "disabled", "tax_category"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.company:
            restaurant = Restaurant.objects.first()
            if restaurant:
                self.instance.company = restaurant.company


class TaxRateForm(SettingsModelForm):
    class Meta:
        model = TaxRate
        fields = [
            "charge_type",
            "rate",
            "account_head",
            "description",
            "cost_center",
            "included_in_print_rate",
            "row_id",
        ]


class POSProfileForm(SettingsModelForm):
    """Form for POSProfile. Branch, restaurant, and company auto-set in save()."""

    class Meta:
        model = POSProfile
        fields = [
            "name",
            "warehouse",
            "disabled",
            "currency",
            "selling_price_list",
            "cost_center",
            "income_account",
            "expense_account",
            "write_off_account",
            "write_off_cost_center",
            "write_off_limit",
            "account_for_change_amount",
            "set_grand_total_to_default_mop",
            "allow_partial_payment",
            "apply_discount_on",
            "enable_discount",
            "action_on_new_invoice",
            "validate_stock_on_save",
            "hide_images",
            "hide_unavailable_items",
            "auto_add_item_to_cart",
            "allow_rate_change",
            "allow_discount_change",
            "allow_warehouse_change",
            "print_receipt_on_order_complete",
            "view_all_status",
            "paid_limit",
            "edit_order_type",
            "remove_items",
            "show_image",
            "require_daily_pos_close",
            "table_attention_time",
            "multiple_cashier",
            "kot_naming_series",
            "reset_order_number_daily",
            "kot_warning_time",
            "notify_kot_delay",
            "enable_kot_reprint",
            "reprint_kot_format",
            "print_format",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = active_choices(Warehouse, self.instance.warehouse_id)
        self.fields["selling_price_list"].queryset = active_choices(PriceList, self.instance.selling_price_list_id)


class POSProfilePaymentForm(SettingsModelForm):
    class Meta:
        model = POSProfilePayment
        fields = ["mode_of_payment", "is_default", "allow_in_returns"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["mode_of_payment"].queryset = active_choices(
            ModeOfPayment, self.instance.mode_of_payment_id, enabled=True
        )


class ProductionUnitForm(SettingsModelForm):
    """Form for ProductionUnit. Branch, warehouse, and pos_profile auto-set in save()."""

    class Meta:
        model = ProductionUnit
        fields = [
            "name",
            "warehouse",
            "department",
            "block_takeaway_kot",
            "printer_ip",
            "printer_paper_width",
            "printer_cut_mode",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = active_choices(Warehouse, self.instance.warehouse_id)

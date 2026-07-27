from django import forms

from apps.users.models import CustomUser

from .models import Branch, Restaurant, Room, Table, UserRoomAssignment

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
        fields = ["company", "invoice_series_prefix", "address", "default_room"]


class UserRoomAssignmentForm(SettingsModelForm):
    """Form for UserRoomAssignment. Branch is derived from room on save."""

    class Meta:
        model = UserRoomAssignment
        fields = ["user", "room"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = CustomUser.objects.order_by("username")

from django import forms

from apps.users.models import CustomUser

from .models import Branch, Restaurant, Room, Table, UserRoomAssignment

TAILWIND_INPUT_CLASS = (
    "w-full rounded-md border border-gray-300 px-3 py-2 text-sm "
    "focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
)


class SettingsModelForm(forms.ModelForm):
    """Base ModelForm that applies Tailwind CSS classes to all fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not field.widget.attrs.get("class"):
                field.widget.attrs["class"] = TAILWIND_INPUT_CLASS


class BranchForm(SettingsModelForm):
    class Meta:
        model = Branch
        fields = ["name", "make_aggregator_unpaid", "no_aggregator_taxes"]


class RoomForm(SettingsModelForm):
    class Meta:
        model = Room
        fields = ["branch", "name", "room_type"]


class TableForm(SettingsModelForm):
    class Meta:
        model = Table
        fields = [
            "room",
            "branch",
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

    def clean(self):
        cleaned_data = super().clean()
        room = cleaned_data.get("room")
        if room:
            cleaned_data["branch"] = room.branch
        return cleaned_data


class RestaurantForm(SettingsModelForm):
    class Meta:
        model = Restaurant
        fields = ["company", "branch", "invoice_series_prefix", "aggregator_series_prefix", "address", "default_room"]


class UserRoomAssignmentForm(SettingsModelForm):
    class Meta:
        model = UserRoomAssignment
        fields = ["user", "room", "branch"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = CustomUser.objects.order_by("username")

    def clean(self):
        cleaned_data = super().clean()
        room = cleaned_data.get("room")
        if room:
            cleaned_data["branch"] = room.branch
        return cleaned_data

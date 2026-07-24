"""Shared form base classes for the backoffice design system."""

from django import forms
from django.db.models import Q

TAILWIND_INPUT_CLASS = (
    "w-full rounded-xl border border-gray-300 bg-white/50 px-4 py-2.5 text-sm "
    "focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-500/25"
)
TAILWIND_CHECKBOX_CLASS = "h-4 w-4 shrink-0 cursor-pointer accent-orange-500"
TAILWIND_FILE_CLASS = (
    "w-full rounded-xl border border-gray-300 bg-white/50 px-3 py-2 text-sm text-gray-600 "
    "file:mr-3 file:rounded-lg file:border-0 file:bg-orange-50 file:px-3 file:py-1.5 "
    "file:text-sm file:font-semibold file:text-orange-600 hover:file:bg-orange-100 "
    "focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-500/25"
)


def active_choices(model_class, current_id=None, **active_filters):
    """Choices for a ModelChoiceField: rows passing ``active_filters``, with
    ``current_id`` always included (so editing a record whose currently-assigned
    FK row is now inactive still shows that option as the selected value in the
    ``<select>``). Use for dropdowns where the source model has a
    ``disabled`` (or similar) flag.
    """
    qs = model_class.objects.filter(**active_filters)
    if current_id:
        return qs | model_class.objects.filter(Q(pk=current_id))
    return qs


class StyledModelForm(forms.ModelForm):
    """ModelForm that applies the backoffice Tailwind design system to every widget.

    - text-like inputs, selects and textareas get the standard input class
    - checkboxes get a compact accent-coloured style (never the full-width input class)
    - file inputs get a styled file-button treatment
    - date fields are rendered with an HTML5 date picker (type="date")
    - ModelChoiceFields get a "Select ..." empty placeholder
    - required ChoiceFields whose model field has no default get a placeholder
      empty option so the user must make an explicit choice
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            self._style_widget(field)
            self._apply_placeholder(name, field)

    def _style_widget(self, field):
        """Apply the appropriate Tailwind class to a field's widget."""
        if isinstance(field, forms.DateField):
            # The "%Y-%m-%d" format ensures edit-form initial values render
            # correctly for the picker; it is already Django's default input
            # format, so parsing is unaffected.
            field.widget = forms.DateInput(
                attrs={"type": "date", "class": TAILWIND_INPUT_CLASS},
                format="%Y-%m-%d",
            )
            return
        widget = field.widget
        if widget.attrs.get("class"):
            return
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs["class"] = TAILWIND_CHECKBOX_CLASS
        elif isinstance(widget, forms.FileInput):
            widget.attrs["class"] = TAILWIND_FILE_CLASS
        else:
            widget.attrs["class"] = TAILWIND_INPUT_CLASS
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)

    def _apply_placeholder(self, name, field):
        """Add a "Select ..." placeholder to choice fields where appropriate."""
        if isinstance(field, forms.ModelChoiceField):
            field.empty_label = f"Select {field.label.lower()}..."
            return
        if not getattr(field, "choices", None) or not field.required:
            return
        model_field = self._get_model_field(name)
        if model_field is None or model_field.has_default():
            return
        if field.choices[0][0] != "":
            field.choices = [("", f"Select {field.label.lower()}..."), *field.choices]

    def _get_model_field(self, name):
        """Return the model field matching a form field name, or None."""
        try:
            return self._meta.model._meta.get_field(name)
        except Exception:
            return None

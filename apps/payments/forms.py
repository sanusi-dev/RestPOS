from apps.utils.forms import StyledModelForm, active_choices

from .models import ModeOfPayment, PaymentGLMapping


class PaymentsModelForm(StyledModelForm):
    """Base ModelForm for payments forms."""


class ModeOfPaymentForm(PaymentsModelForm):
    class Meta:
        model = ModeOfPayment
        fields = ["name", "type", "enabled", "is_default"]


class PaymentGLMappingForm(PaymentsModelForm):
    class Meta:
        model = PaymentGLMapping
        fields = ["mode_of_payment", "default_account"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Show enabled modes in the dropdown by default, but keep the currently-assigned
        # (now disabled) one visible when editing.
        self.fields["mode_of_payment"].queryset = active_choices(
            ModeOfPayment, self.instance.mode_of_payment_id, enabled=True
        )

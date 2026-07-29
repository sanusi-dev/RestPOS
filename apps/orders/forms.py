from apps.utils.forms import StyledModelForm, active_choices

from .models import Order, OrderItem, OrderPayment


class OrderForm(StyledModelForm):
    class Meta:
        model = Order
        fields = [
            "order_type",
            "table",
            "customer_name",
            "customer_mobile",
            "guest_count",
            "comments",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.settings.models import Table

        self.fields["table"].queryset = active_choices(Table, self.instance.table_id)

    def clean(self):
        cleaned = super().clean()
        order_type = cleaned.get("order_type")
        table = cleaned.get("table")
        if order_type == "DINE_IN" and not table:
            self.add_error("table", "A table is required for dine-in orders.")
        return cleaned


class OrderItemForm(StyledModelForm):
    class Meta:
        model = OrderItem
        fields = ["item", "qty", "rate", "customer_index", "comments"]


class OrderPaymentForm(StyledModelForm):
    class Meta:
        model = OrderPayment
        fields = ["mode_of_payment", "amount", "reference_no"]

from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from apps.accounting.models import LedgerAccount
from apps.utils.forms import StyledModelForm, active_choices

from .models import (
    UOM,
    Item,
    ItemGroup,
    PurchaseReceipt,
    PurchaseReceiptItem,
    StockEntry,
    StockEntryDetail,
    StockReconciliation,
    StockReconciliationItem,
    Warehouse,
)


class InventoryModelForm(StyledModelForm):
    """Base ModelForm for inventory forms."""


class UOMForm(InventoryModelForm):
    class Meta:
        model = UOM
        fields = ["name"]


class ItemGroupForm(InventoryModelForm):
    class Meta:
        model = ItemGroup
        fields = ["name", "description"]


class WarehouseForm(InventoryModelForm):
    class Meta:
        model = Warehouse
        fields = ["name", "disabled", "account"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs["placeholder"] = "e.g. Main Store"
        self.fields["disabled"].label = "Disable this warehouse"
        self.fields["disabled"].help_text = (
            "When enabled, this warehouse will be unavailable for new inventory activity. "
            "Configured Store, Bar, or Kitchen warehouses cannot be disabled."
        )
        self.fields["account"].queryset = active_choices(
            LedgerAccount, self.instance.account_id, disabled=False, is_group=False
        )


class ItemForm(InventoryModelForm):
    class Meta:
        model = Item
        fields = [
            "item_name",
            "item_group",
            "stock_uom",
            "department",
            "image",
            "description",
            "disabled",
            "is_stock_item",
            "is_sales_item",
            "is_purchase_item",
            "has_variants",
            "variant_of",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item_name"].widget.attrs["placeholder"] = "e.g. Jollof Rice"
        self.fields["description"].widget.attrs["placeholder"] = (
            "e.g. Long-grain rice served with tomato stew and grilled chicken."
        )
        department_choices = list(self.fields["department"].choices)
        department_choices[0] = ("", "Select a department...")
        self.fields["department"].choices = department_choices

        checkbox_copy = {
            "is_stock_item": (
                "Track stock levels",
                "When enabled, this item’s stock quantity and inventory movements will be tracked automatically.",
            ),
            "is_sales_item": (
                "Sell this item",
                "When enabled, this item can be added to menus and sold through the POS.",
            ),
            "is_purchase_item": (
                "Buy this item",
                "When enabled, this item can be included on purchase receipts.",
            ),
            "disabled": (
                "Pause this item",
                "When enabled, this item will be hidden from new orders and purchases.",
            ),
            "has_variants": (
                "Use variants",
                "When enabled, this item becomes a template for variants and cannot be stocked, sold, or purchased directly.",
            ),
        }
        for field_name, (label, help_text) in checkbox_copy.items():
            self.fields[field_name].label = label
            self.fields[field_name].help_text = help_text

        # Keep any currently-assigned (now disabled) row visible when editing.
        self.fields["variant_of"].queryset = active_choices(
            Item, self.instance.variant_of_id, disabled=False, has_variants=True
        )

    def clean(self):
        cleaned = super().clean()
        dept = cleaned.get("department") or getattr(self.instance, "department", None)
        is_stock = cleaned.get("is_stock_item")
        is_sales = cleaned.get("is_sales_item")
        is_purch = cleaned.get("is_purchase_item")
        has_variants = cleaned.get("has_variants")
        if has_variants:
            return cleaned
        if dept == "DRINKS" and is_stock is not None and is_sales is not None and is_purch is not None:
            if not (is_stock and is_sales and is_purch):
                raise ValidationError("Drinks items must be stock-tracked, sellable, and purchasable.")
        elif dept == "FOOD" and is_stock is not None and is_sales is not None and is_purch is not None:
            if is_sales:
                if is_stock or is_purch:
                    raise ValidationError(
                        "Sellable food items are virtual — they must not be stock-tracked or purchasable."
                    )
            else:
                if not (is_stock and is_purch):
                    raise ValidationError("Non-sellable food items must be stock-tracked and purchasable.")
        return cleaned


class StockEntryForm(InventoryModelForm):
    class Meta:
        model = StockEntry
        fields = ["purpose", "posting_date", "remarks"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = list(self.fields["purpose"].choices)
        if choices and choices[0][0] == "":
            choices[0] = ("", "Select purpose...")
        else:
            choices.insert(0, ("", "Select purpose..."))
        self.fields["purpose"].choices = choices


class StockEntryDetailForm(InventoryModelForm):
    class Meta:
        model = StockEntryDetail
        fields = ["item", "qty", "basic_rate"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        purpose = self.data.get("purpose") if self.is_bound else None
        self.fields["item"].queryset = active_choices(Item, self.instance.item_id, disabled=False, is_stock_item=True)
        self.fields["basic_rate"].initial = None
        self.fields["basic_rate"].required = purpose != "MATERIAL_TRANSFER"
        self.fields["basic_rate"].widget.attrs["x-bind:disabled"] = "purpose === 'MATERIAL_TRANSFER'"


class StockReconciliationForm(InventoryModelForm):
    class Meta:
        model = StockReconciliation
        fields = ["purpose", "reason", "posting_date", "warehouse", "remarks"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = active_choices(Warehouse, self.instance.warehouse_id, disabled=False)
        choices = list(self.fields["reason"].choices)
        if choices and choices[0][0] == "":
            choices[0] = ("", "Select reason...")
        else:
            choices.insert(0, ("", "Select reason..."))
        self.fields["reason"].choices = choices

    def clean(self):
        cleaned_data = super().clean()
        purpose = cleaned_data.get("purpose")
        reason = cleaned_data.get("reason")
        if purpose == "OPENING_STOCK" and reason != "OPENING_STOCK":
            self.add_error("reason", "Opening Stock must use the Opening Stock reason.")
        elif purpose == "RECONCILIATION" and reason == "OPENING_STOCK":
            self.add_error("reason", "Opening Stock reason is only valid for Opening Stock purpose.")
        return cleaned_data


class StockReconciliationItemForm(InventoryModelForm):
    class Meta:
        model = StockReconciliationItem
        fields = ["item", "qty", "valuation_rate"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = active_choices(Item, self.instance.item_id, disabled=False, is_stock_item=True)
        self.fields["valuation_rate"].widget.attrs["x-bind:disabled"] = "purpose !== 'OPENING_STOCK'"


class PurchaseReceiptForm(InventoryModelForm):
    class Meta:
        model = PurchaseReceipt
        fields = [
            "supplier_name",
            "supplier",
            "supplier_delivery_note",
            "posting_date",
            "remarks",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounting.models import Supplier

        self.fields["supplier"].queryset = active_choices(Supplier, self.instance.supplier_id, disabled=False)
        self.fields["supplier"].required = False
        # Required-ness depends on the supplier choice — enforced in clean().
        self.fields["supplier_name"].required = False

    def clean(self):
        cleaned_data = super().clean()
        from apps.settings.models import Restaurant

        restaurant = Restaurant.load()
        if not restaurant or not restaurant.store_warehouse_id or restaurant.store_warehouse.disabled:
            raise ValidationError("Configure an enabled central Store warehouse before creating a purchase receipt.")
        # Selecting a Supplier master fills supplier_name so the receipt stays readable on its own.
        if not cleaned_data.get("supplier_name") and cleaned_data.get("supplier"):
            cleaned_data["supplier_name"] = cleaned_data["supplier"].supplier_name
        elif not cleaned_data.get("supplier_name"):
            self.add_error("supplier_name", "This field is required.")
        self.instance.warehouse = restaurant.store_warehouse
        return cleaned_data


class PurchaseReceiptItemForm(InventoryModelForm):
    class Meta:
        model = PurchaseReceiptItem
        fields = ["item", "received_qty", "rate"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = active_choices(
            Item,
            self.instance.item_id,
            disabled=False,
            is_stock_item=True,
            is_purchase_item=True,
        )


StockEntryDetailFormSet = inlineformset_factory(
    StockEntry, StockEntryDetail, form=StockEntryDetailForm, extra=1, can_delete=True
)
StockReconciliationItemFormSet = inlineformset_factory(
    StockReconciliation,
    StockReconciliationItem,
    form=StockReconciliationItemForm,
    extra=1,
    can_delete=True,
)
PurchaseReceiptItemFormSet = inlineformset_factory(
    PurchaseReceipt, PurchaseReceiptItem, form=PurchaseReceiptItemForm, extra=1, can_delete=True
)

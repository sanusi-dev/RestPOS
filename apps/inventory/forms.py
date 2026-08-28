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
        fields = ["name", "description", "income_account", "expense_account"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("income_account", "expense_account"):
            self.fields[field_name].queryset = active_choices(
                LedgerAccount, getattr(self.instance, f"{field_name}_id"), disabled=False, is_group=False
            )


class WarehouseForm(InventoryModelForm):
    class Meta:
        model = Warehouse
        fields = ["name", "disabled", "account"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
            "default_warehouse",
            "has_variants",
            "variant_of",
            "safety_stock",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep any currently-assigned (now disabled) row visible when editing.
        self.fields["variant_of"].queryset = active_choices(
            Item, self.instance.variant_of_id, disabled=False, has_variants=True
        )
        self.fields["default_warehouse"].queryset = active_choices(
            Warehouse, self.instance.default_warehouse_id, disabled=False
        )


class StockEntryForm(InventoryModelForm):
    class Meta:
        model = StockEntry
        fields = ["purpose", "posting_date", "remarks"]


class StockEntryDetailForm(InventoryModelForm):
    class Meta:
        model = StockEntryDetail
        fields = ["item", "qty", "basic_rate"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        filters = {"disabled": False, "is_stock_item": True, "has_variants": False}
        purpose = self.data.get("purpose") if self.is_bound else None
        stock_entry = getattr(self.instance, "stock_entry", None)
        if not purpose and stock_entry:
            purpose = stock_entry.purpose
        if purpose == "MATERIAL_RECEIPT":
            filters["is_purchase_item"] = True
        self.fields["item"].queryset = active_choices(Item, self.instance.item_id, **filters)


class StockReconciliationForm(InventoryModelForm):
    class Meta:
        model = StockReconciliation
        fields = ["purpose", "reason", "posting_date", "warehouse", "remarks"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = active_choices(Warehouse, self.instance.warehouse_id, disabled=False)


class StockReconciliationItemForm(InventoryModelForm):
    class Meta:
        model = StockReconciliationItem
        fields = ["item", "qty", "valuation_rate"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = active_choices(
            Item, self.instance.item_id, disabled=False, is_stock_item=True, has_variants=False
        )


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
            has_variants=False,
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

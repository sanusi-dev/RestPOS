from django.forms import inlineformset_factory

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
    """Form for Warehouse. Branch is auto-assigned on save."""

    class Meta:
        model = Warehouse
        fields = ["name", "disabled"]


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
        # Filter dropdowns to active rows, keeping any currently-assigned (now disabled)
        # row visible in the <select> when editing.
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
        fields = [
            "item",
            "source_warehouse",
            "target_warehouse",
            "qty",
            "basic_rate",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = active_choices(Item, self.instance.item_id, disabled=False)
        self.fields["source_warehouse"].queryset = active_choices(
            Warehouse, self.instance.source_warehouse_id, disabled=False
        )
        self.fields["target_warehouse"].queryset = active_choices(
            Warehouse, self.instance.target_warehouse_id, disabled=False
        )


class StockReconciliationForm(InventoryModelForm):
    class Meta:
        model = StockReconciliation
        fields = ["purpose", "posting_date", "warehouse", "remarks"]


class StockReconciliationItemForm(InventoryModelForm):
    class Meta:
        model = StockReconciliationItem
        fields = ["item", "warehouse", "qty", "valuation_rate"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = active_choices(Item, self.instance.item_id, disabled=False)
        self.fields["warehouse"].queryset = active_choices(Warehouse, self.instance.warehouse_id, disabled=False)


class PurchaseReceiptForm(InventoryModelForm):
    class Meta:
        model = PurchaseReceipt
        fields = [
            "supplier_name",
            "supplier_delivery_note",
            "posting_date",
            "warehouse",
            "remarks",
        ]


class PurchaseReceiptItemForm(InventoryModelForm):
    class Meta:
        model = PurchaseReceiptItem
        fields = ["item", "received_qty", "rate"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = active_choices(
            Item, self.instance.item_id, disabled=False, is_purchase_item=True, has_variants=False
        )


# ---------------------------------------------------------------------------

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

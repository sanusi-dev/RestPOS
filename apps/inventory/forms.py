from django import forms
from django.forms import inlineformset_factory

from .models import (
    UOM,
    Batch,
    Item,
    ItemBarcode,
    ItemGroup,
    ItemUOMConversion,
    ProductBundle,
    ProductBundleItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    ReorderLevel,
    StockEntry,
    StockEntryDetail,
    StockReconciliation,
    StockReconciliationItem,
    Warehouse,
)

TAILWIND_INPUT_CLASS = (
    "w-full rounded-md border border-gray-300 px-3 py-2 text-sm "
    "focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
)


class InventoryModelForm(forms.ModelForm):
    """Base ModelForm that applies Tailwind CSS classes to all fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not field.widget.attrs.get("class"):
                field.widget.attrs["class"] = TAILWIND_INPUT_CLASS


class UOMForm(InventoryModelForm):
    class Meta:
        model = UOM
        fields = ["name", "is_active"]


class ItemGroupForm(InventoryModelForm):
    class Meta:
        model = ItemGroup
        fields = ["name", "parent", "is_group", "description"]


class WarehouseForm(InventoryModelForm):
    class Meta:
        model = Warehouse
        fields = ["name", "branch", "parent", "is_group", "is_rejected", "disabled"]


class ItemForm(InventoryModelForm):
    class Meta:
        model = Item
        fields = [
            "item_code",
            "item_name",
            "item_group",
            "stock_uom",
            "department",
            "image",
            "description",
            "disabled",
            "is_stock_item",
            "default_warehouse",
            "valuation_method",
            "has_batch_no",
            "has_expiry_date",
            "shelf_life_in_days",
            "has_variants",
            "variant_of",
            "safety_stock",
            "lead_time_days",
            "end_of_life",
            "standard_rate",
        ]


class BatchForm(InventoryModelForm):
    class Meta:
        model = Batch
        fields = ["batch_id", "item", "expiry_date", "manufacturing_date"]


class ProductBundleForm(InventoryModelForm):
    class Meta:
        model = ProductBundle
        fields = ["parent_item", "is_active"]


class ProductBundleItemForm(InventoryModelForm):
    class Meta:
        model = ProductBundleItem
        fields = ["item", "qty"]


class StockEntryForm(InventoryModelForm):
    class Meta:
        model = StockEntry
        fields = ["purpose", "posting_date", "from_warehouse", "to_warehouse", "remarks"]


class StockEntryDetailForm(InventoryModelForm):
    class Meta:
        model = StockEntryDetail
        fields = [
            "item",
            "source_warehouse",
            "target_warehouse",
            "qty",
            "uom",
            "conversion_factor",
            "basic_rate",
            "batch",
        ]


class StockReconciliationForm(InventoryModelForm):
    class Meta:
        model = StockReconciliation
        fields = ["purpose", "posting_date", "warehouse", "remarks"]


class StockReconciliationItemForm(InventoryModelForm):
    class Meta:
        model = StockReconciliationItem
        fields = ["item", "warehouse", "qty", "valuation_rate"]


class PurchaseReceiptForm(InventoryModelForm):
    class Meta:
        model = PurchaseReceipt
        fields = [
            "supplier_name",
            "supplier_delivery_note",
            "posting_date",
            "accepted_warehouse",
            "rejected_warehouse",
            "remarks",
        ]


class PurchaseReceiptItemForm(InventoryModelForm):
    class Meta:
        model = PurchaseReceiptItem
        fields = ["item", "received_qty", "rejected_qty", "uom", "rate", "batch", "warehouse"]


# ---------------------------------------------------------------------------
# Inline formsets
# ---------------------------------------------------------------------------

ItemBarcodeFormSet = inlineformset_factory(
    Item, ItemBarcode, fields=["barcode", "barcode_type"], extra=1, can_delete=True
)
ItemUOMConversionFormSet = inlineformset_factory(
    Item, ItemUOMConversion, fields=["uom", "conversion_factor"], extra=1, can_delete=True
)
ReorderLevelFormSet = inlineformset_factory(
    Item, ReorderLevel, fields=["warehouse", "reorder_level", "reorder_qty"], extra=1, can_delete=True
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
ProductBundleItemFormSet = inlineformset_factory(
    ProductBundle, ProductBundleItem, form=ProductBundleItemForm, extra=1, can_delete=True
)
PurchaseReceiptItemFormSet = inlineformset_factory(
    PurchaseReceipt, PurchaseReceiptItem, form=PurchaseReceiptItemForm, extra=1, can_delete=True
)

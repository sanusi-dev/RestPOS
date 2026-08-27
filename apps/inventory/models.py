from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.utils.models import BaseModel


class InsufficientStock(ValidationError):
    """Raised when an outbound would drive Bin.actual_qty negative."""


def _assert_document_is_draft(document, *, action="modify"):
    """Reject mutations on submitted or cancelled inventory documents."""
    if document is None or not document.pk:
        return
    status = type(document).objects.only("status").get(pk=document.pk).status
    if status != "DRAFT":
        raise ValidationError(f"Cannot {action} a {status.lower()} inventory document.")


class UOM(BaseModel):
    """Unit of measure (e.g. Nos, Kg, Litre, Box)."""

    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ItemGroup(BaseModel):
    """A product category (e.g. Food, Drinks, Proteins)."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    income_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Income account",
    )
    expense_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Expense account",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Warehouse(BaseModel):
    """A stock location (e.g. Main Store, Kitchen Store, Bar Store)."""

    name = models.CharField(max_length=100, unique=True)
    disabled = models.BooleanField(default=False)
    account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Account",
        help_text="Credited with the stock value of settle-time drink deductions.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if not self.disabled or not self.pk:
            return

        from apps.settings.models import ProductionUnit, Restaurant

        configured_as = []
        if Restaurant.objects.filter(default_warehouse_id=self.pk).exists():
            configured_as.append("Bar / POS sales warehouse")
        if Restaurant.objects.filter(store_warehouse_id=self.pk).exists():
            configured_as.append("central Store warehouse")
        if ProductionUnit.objects.filter(warehouse_id=self.pk).exists():
            configured_as.append("production unit warehouse")
        if configured_as:
            raise ValidationError({"disabled": f"Cannot disable a configured {', '.join(configured_as)}."})


class Item(BaseModel):
    """A product or material tracked in inventory and sold via POS."""

    item_code = models.CharField(max_length=50, unique=True, blank=True)
    item_name = models.CharField(max_length=200)
    item_group = models.ForeignKey(ItemGroup, on_delete=models.PROTECT, related_name="items")
    stock_uom = models.ForeignKey(UOM, on_delete=models.PROTECT, related_name="items")
    department = models.CharField(
        max_length=10,
        choices=[("FOOD", "Food"), ("DRINKS", "Drinks")],
    )
    image = models.ImageField(upload_to="items/", default="items/default-item.png", blank=True)
    description = models.TextField(blank=True)
    disabled = models.BooleanField(default=False)
    is_stock_item = models.BooleanField(default=True)
    is_sales_item = models.BooleanField(
        default=False,
        help_text="If true, this item may be added to a menu and sold on the POS.",
    )
    is_purchase_item = models.BooleanField(
        default=False,
        help_text="If true, this item may appear on purchase receipts.",
    )
    default_warehouse = models.ForeignKey(
        Warehouse,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="default_items",
    )
    has_variants = models.BooleanField(default=False)
    variant_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="variants",
    )
    safety_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    last_purchase_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["item_name"]

    def __str__(self):
        return self.item_name or self.item_code

    def save(self, *args, **kwargs):
        if self.has_variants:
            # Templates are structure only — never stocked or sold as a line (ERPNext-aligned).
            self.is_stock_item = False
            self.is_sales_item = False
            self.is_purchase_item = False
        if not self.pk and not self.item_code:
            with transaction.atomic():
                last = Item.objects.select_for_update().filter(item_code__regex=r"^ITEM-\d+$").order_by("-pk").first()
                num = 1 if last is None else int(last.item_code.split("-")[1]) + 1
                self.item_code = f"ITEM-{num:04d}"
            super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)
        # Non-sellable items cannot remain POS add-ons (price/sales path is invalid).
        if not self.is_sales_item and self.pk:
            from apps.menu.models import ItemAddOn

            ItemAddOn.objects.filter(add_on_item_id=self.pk).delete()

    def clean(self):
        super().clean()
        if self.has_variants and self.is_stock_item:
            raise ValidationError("Template items with variants cannot maintain stock")
        if self.has_variants and (self.is_sales_item or self.is_purchase_item):
            raise ValidationError("Template items cannot be sold or purchased — sell/buy the size variants instead.")
        if self.variant_of_id and not self.variant_of.has_variants:
            raise ValidationError("Parent item must have has_variants=True")
        if self.pk and not self.is_sales_item:
            from apps.menu.models import MenuItem

            if MenuItem.objects.filter(item_id=self.pk, disabled=False).exists():
                raise ValidationError(
                    {
                        "is_sales_item": (
                            "This item is still on an enabled menu. "
                            "Disable or remove those menu lines before turning off Sellable."
                        )
                    }
                )


class Bin(BaseModel):
    """The current stock snapshot for a single item in a single warehouse."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="bins")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="bins")
    actual_qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    reserved_qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    valuation_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    class Meta:
        unique_together = [("item", "warehouse")]

    def __str__(self):
        return f"{self.item.item_code} @ {self.warehouse.name}: {self.actual_qty}"

    @property
    def stock_value(self):
        """Derived stock value (qty × WAC) for template/admin compatibility."""
        qty = self.actual_qty or Decimal("0")
        wac = self.valuation_rate or Decimal("0")
        return qty * wac

    @classmethod
    def get_or_create_bin(cls, item, warehouse):
        """Return the existing Bin for item+warehouse, or create a new one."""
        bin_obj, _created = cls.objects.get_or_create(item=item, warehouse=warehouse)
        return bin_obj

    @classmethod
    def get_or_create_bin_id(cls, item_id, warehouse_id):
        """Same as get_or_create_bin but takes ids directly — skips FK instance loads."""
        bin_obj, _created = cls.objects.get_or_create(item_id=item_id, warehouse_id=warehouse_id)
        return bin_obj


class StockLedgerEntry(BaseModel):
    """An immutable record of a single stock movement for one item in one warehouse.

    This is the core of the inventory ledger — every stock change creates one
    or more SLE rows. Submitted documents are never edited; cancellation
    creates reversal entries via reversal_of_sle.
    """

    VARIANCE_CHOICES = [
        ("CANCELLATION_WAC", "Cancellation WAC"),
        ("SALE_RETURN", "Sale Return"),
    ]

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="stock_ledger_entries")
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="stock_ledger_entries",
    )
    # Business date — always pass the voucher's posting_date explicitly; default is fallback.
    posting_date = models.DateField(default=timezone.localdate, editable=False)
    posting_datetime = models.DateTimeField(auto_now_add=True, editable=False)
    voucher_type = models.CharField(max_length=50)
    voucher_no = models.CharField(max_length=100)
    voucher_detail_no = models.CharField(max_length=100, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    unit_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"), editable=False)
    stock_value_change = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    variance_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    variance_type = models.CharField(
        max_length=20,
        choices=VARIANCE_CHOICES,
        blank=True,
        default="",
        editable=False,
    )
    reversal_of_sle = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reversals",
        editable=False,
    )

    class Meta:
        ordering = ["-posting_datetime"]
        indexes = [models.Index(fields=["item", "warehouse", "-posting_datetime"])]

    def __str__(self):
        sign = "+" if self.quantity >= 0 else ""
        return f"{sign}{self.quantity} {self.item.item_code} @ {self.warehouse.name}"

    @classmethod
    def create_entry(
        cls,
        item,
        warehouse,
        quantity=None,
        voucher_type="",
        voucher_no="",
        *,
        unit_rate=None,
        voucher_detail_no="",
        prevent_negative=False,
        posting_date=None,
        variance_amount=Decimal("0"),
        variance_type="",
        reversal_of_sle_id=None,
    ):
        """Create a ledger entry and update the corresponding Bin.

        ``quantity`` is signed: positive for receipts, negative for issues.
        ``unit_rate`` is the inbound rate (ignored for outbound where WAC supplies it).
        """
        if quantity is None:
            raise ValidationError("quantity is required")
        quantity = Decimal(str(quantity))
        if unit_rate is not None:
            unit_rate = Decimal(str(unit_rate))
        if variance_amount is not None:
            variance_amount = Decimal(str(variance_amount))
        with transaction.atomic():
            bin_obj = Bin.get_or_create_bin(item, warehouse)
            bin_obj = Bin.objects.select_for_update().get(pk=bin_obj.pk)
            return cls._create_entry_locked(
                item=item,
                warehouse=warehouse,
                quantity=quantity,
                voucher_type=voucher_type,
                voucher_no=voucher_no,
                unit_rate=unit_rate,
                voucher_detail_no=voucher_detail_no,
                prevent_negative=prevent_negative,
                posting_date=posting_date,
                variance_amount=variance_amount,
                variance_type=variance_type,
                reversal_of_sle_id=reversal_of_sle_id,
                bin_obj=bin_obj,
            )

    @classmethod
    def _create_entry_locked(
        cls,
        *,
        item,
        warehouse,
        quantity,
        voucher_type,
        voucher_no,
        unit_rate,
        voucher_detail_no,
        prevent_negative,
        bin_obj,
        posting_date=None,
        variance_amount=Decimal("0"),
        variance_type="",
        reversal_of_sle_id=None,
    ):
        quantity = Decimal(str(quantity))
        if unit_rate is not None:
            unit_rate = Decimal(str(unit_rate))
        variance_amount = Decimal("0") if variance_amount is None else Decimal(str(variance_amount))
        variance_type = variance_type or ""

        # Posting date is business/audit date — copy of voucher posting_date.
        # Always blend at current WAC; posting_date never affects valuation.
        if posting_date is None:
            posting_date = timezone.localdate()
        if isinstance(posting_date, str):
            posting_date = date.fromisoformat(posting_date)
        # Future-dated transactions are rejected.
        if posting_date > timezone.localdate():
            raise ValidationError("Posting date cannot be in the future.")

        current_qty = bin_obj.actual_qty or Decimal("0")
        wac = bin_obj.valuation_rate or Decimal("0")
        quantity = Decimal(quantity)

        # Enforce non-negative stock everywhere (perpetual WAC invariant).
        new_qty = current_qty + quantity
        if new_qty < 0:
            raise InsufficientStock(f"Insufficient stock for {item.item_name} in {warehouse.name}.")

        stock_value_change = Decimal("0")
        resolved_rate = Decimal("0")

        if quantity > 0:
            # Inbound: blend at resolved_rate. If caller didn't supply a rate
            # (e.g. restores at current WAC), use current WAC — identity blend.
            resolved_rate = wac if unit_rate is None else unit_rate
            if resolved_rate < 0:
                raise ValidationError("Unit rate cannot be negative.")
            inbound_value = quantity * resolved_rate
            new_wac = (current_qty * wac + inbound_value) / new_qty if new_qty != 0 else Decimal("0")
            stock_value_change = inbound_value
            bin_obj.valuation_rate = new_wac
        elif quantity < 0:
            # Outbound: always at current WAC; WAC unchanged.
            resolved_rate = wac
            stock_value_change = quantity * wac  # negative
        else:
            raise ValidationError("Quantity cannot be zero.")

        sle = cls.objects.create(
            item=item,
            warehouse=warehouse,
            quantity=quantity,
            unit_rate=resolved_rate,
            stock_value_change=stock_value_change,
            variance_amount=variance_amount,
            variance_type=variance_type,
            reversal_of_sle_id=reversal_of_sle_id,
            voucher_type=voucher_type,
            voucher_no=voucher_no,
            voucher_detail_no=voucher_detail_no,
            posting_date=posting_date,
        )

        bin_obj.actual_qty = new_qty
        # valuation_rate already updated for inbound; outbound keeps it.
        bin_obj.save(update_fields=["actual_qty", "valuation_rate", "reserved_qty", "updated_at"])

        return sle


class StockEntry(BaseModel):
    """A stock receipt or Store-to-production-unit transfer."""

    purpose = models.CharField(
        max_length=30,
        choices=[
            ("MATERIAL_RECEIPT", "Material Receipt"),
            ("MATERIAL_TRANSFER", "Material Transfer"),
        ],
    )
    posting_date = models.DateField(default=timezone.now)
    status = models.CharField(
        max_length=10,
        choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("CANCELLED", "Cancelled")],
        default="DRAFT",
    )
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-posting_date", "-created_at"]

    def __str__(self):
        return f"{self.purpose} - {self.posting_date}"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.only("status").get(pk=self.pk)
            if previous.status != "DRAFT" and self.status == previous.status:
                raise ValidationError(f"Cannot modify a {previous.status.lower()} stock entry.")
            if previous.status != "DRAFT" and self.status not in {"SUBMITTED", "CANCELLED"}:
                raise ValidationError(f"Cannot modify a {previous.status.lower()} stock entry.")
            if previous.status == "SUBMITTED" and self.status not in {"SUBMITTED", "CANCELLED"}:
                raise ValidationError("Submitted stock entries can only be cancelled.")
            if previous.status == "CANCELLED" and self.status != "CANCELLED":
                raise ValidationError("Cancelled stock entries cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk:
            _assert_document_is_draft(self, action="delete")
        return super().delete(*args, **kwargs)

    @staticmethod
    def stock_ledger_entries_for_voucher(voucher_no):
        return StockLedgerEntry.objects.select_related("item", "warehouse").filter(
            voucher_type="Stock Entry", voucher_no=voucher_no
        )


class StockEntryDetail(BaseModel):
    """A single line item of a stock entry."""

    stock_entry = models.ForeignKey(StockEntry, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="stock_entry_details")
    source_warehouse = models.ForeignKey(
        Warehouse,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outgoing_details",
    )
    target_warehouse = models.ForeignKey(
        Warehouse,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="incoming_details",
    )
    qty = models.DecimalField(max_digits=10, decimal_places=2)
    basic_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    def __str__(self):
        return f"{self.item.item_code} x{self.qty}"

    def save(self, *args, **kwargs):
        if self.stock_entry_id:
            _assert_document_is_draft(self.stock_entry, action="modify lines on")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.stock_entry_id:
            _assert_document_is_draft(self.stock_entry, action="delete lines from")
        return super().delete(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.stock_entry_id:
            return
        purpose = self.stock_entry.purpose
        if purpose == "MATERIAL_RECEIPT":
            if self.source_warehouse_id:
                raise ValidationError({"source_warehouse": "Material Receipt should not have a source warehouse."})
        elif (
            purpose == "MATERIAL_TRANSFER"
            and self.source_warehouse_id == self.target_warehouse_id
            and self.source_warehouse_id
        ):
            raise ValidationError("Source and target warehouses must differ.")

    def validate_for_submission(self, *, restaurant, targets):
        if self.qty <= 0:
            raise ValidationError(f"Quantity for {self.item.item_name} must be greater than zero.")
        if self.item.disabled or not self.item.is_stock_item or self.item.has_variants:
            raise ValidationError(f"{self.item.item_name} is not an enabled stock item.")
        if self.stock_entry.purpose == "MATERIAL_RECEIPT":
            if not self.item.is_purchase_item:
                raise ValidationError(f"{self.item.item_name} is not purchasable.")
            if self.source_warehouse_id:
                raise ValidationError("Material Receipt cannot have a source warehouse.")
            if self.target_warehouse_id and self.target_warehouse_id != restaurant.store_warehouse_id:
                raise ValidationError("Material Receipt target must be the configured central Store.")
        else:
            target = targets[self.item.department]
            if self.source_warehouse_id and self.source_warehouse_id != restaurant.store_warehouse_id:
                raise ValidationError("Material Transfer source must be the configured central Store.")
            if self.target_warehouse_id and self.target_warehouse_id != target.pk:
                raise ValidationError(f"{self.item.item_name} must transfer to {target.name}.")


class StockReconciliation(BaseModel):
    """A document that adjusts stock to match a physical count."""

    purpose = models.CharField(
        max_length=20,
        choices=[("OPENING_STOCK", "Opening Stock"), ("RECONCILIATION", "Stock Reconciliation")],
        default="RECONCILIATION",
    )
    reason = models.CharField(
        max_length=20,
        choices=[
            ("PHYSICAL_COUNT", "Physical Count"),
            ("CONSUMPTION", "Consumption"),
            ("WASTE_DAMAGE", "Waste / Damage"),
            ("CORRECTION", "Correction"),
        ],
    )
    posting_date = models.DateField(default=timezone.now)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="reconciliations")
    status = models.CharField(
        max_length=10,
        choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("CANCELLED", "Cancelled")],
        default="DRAFT",
    )
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-posting_date", "-created_at"]

    def __str__(self):
        return f"{self.get_purpose_display()} - {self.warehouse.name} - {self.posting_date}"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.only("status").get(pk=self.pk)
            if previous.status != "DRAFT" and self.status == previous.status:
                raise ValidationError(f"Cannot modify a {previous.status.lower()} stock reconciliation.")
            if previous.status == "SUBMITTED" and self.status not in {"SUBMITTED", "CANCELLED"}:
                raise ValidationError("Submitted reconciliations can only be cancelled.")
            if previous.status == "CANCELLED" and self.status != "CANCELLED":
                raise ValidationError("Cancelled reconciliations cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk:
            _assert_document_is_draft(self, action="delete")
        return super().delete(*args, **kwargs)


class StockReconciliationItem(BaseModel):
    """A single line item of a stock reconciliation (one item's counted qty)."""

    reconciliation = models.ForeignKey(
        StockReconciliation,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=10, decimal_places=2)
    current_qty = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        editable=False,
    )
    valuation_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.item.item_code}: {self.qty}"

    def save(self, *args, **kwargs):
        if self.reconciliation_id:
            _assert_document_is_draft(self.reconciliation, action="modify lines on")
        if not self.pk and self.item_id and self.reconciliation_id:
            bin_obj = Bin.get_or_create_bin_id(self.item_id, self.reconciliation.warehouse_id)
            self.current_qty = bin_obj.actual_qty
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.reconciliation_id:
            _assert_document_is_draft(self.reconciliation, action="delete lines from")
        return super().delete(*args, **kwargs)


class PurchaseReceipt(BaseModel):
    """Records the receipt of goods from a supplier (FEATURES.md #123).

    When a delivery arrives the storekeeper creates a purchase receipt listing
    items, quantities and rates. On submit it increases stock in the receipt's
    warehouse (via Stock Ledger Entries). The whole receipt goes to one store
    room — further movement (e.g. store → kitchen) is done with Stock Entry.
    Only quantities that enter stock are recorded; damaged/refused goods are
    omitted (or written off later via Stock Reconciliation).
    """

    supplier_name = models.CharField(max_length=200)
    supplier = models.ForeignKey(
        "accounting.Supplier",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_receipts",
        verbose_name="Supplier",
        help_text="Optional link to the Supplier master; the receipt keeps its free-text name for quick entry.",
    )
    supplier_delivery_note = models.CharField(max_length=100, blank=True)
    posting_date = models.DateField(default=timezone.now)
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="purchase_receipts",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=10,
        choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("CANCELLED", "Cancelled")],
        default="DRAFT",
    )
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-posting_date", "-created_at"]

    def __str__(self):
        return f"PR - {self.supplier_name} - {self.posting_date}"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.only("status").get(pk=self.pk)
            if previous.status != "DRAFT" and self.status == previous.status:
                raise ValidationError(f"Cannot modify a {previous.status.lower()} purchase receipt.")
            if previous.status == "SUBMITTED" and self.status not in {"SUBMITTED", "CANCELLED"}:
                raise ValidationError("Submitted purchase receipts can only be cancelled.")
            if previous.status == "CANCELLED" and self.status != "CANCELLED":
                raise ValidationError("Cancelled purchase receipts cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk:
            _assert_document_is_draft(self, action="delete")
        return super().delete(*args, **kwargs)

    def clean(self):
        super().clean()
        from apps.settings.models import Restaurant

        restaurant = Restaurant.load()
        if (
            self.warehouse_id
            and restaurant
            and restaurant.store_warehouse_id
            and self.warehouse_id != restaurant.store_warehouse_id
        ):
            raise ValidationError({"warehouse": "Purchase Receipt warehouse must be the configured central Store."})


class PurchaseReceiptItem(BaseModel):
    """A single line item of a purchase receipt.

    Warehouse is on the parent PurchaseReceipt — every line posts to the same store.
    """

    purchase_receipt = models.ForeignKey(
        PurchaseReceipt,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="purchase_receipt_items")
    received_qty = models.DecimalField(max_digits=10, decimal_places=2)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)

    def __str__(self):
        return f"{self.item.item_code} x{self.received_qty}"

    def save(self, *args, **kwargs):
        if self.purchase_receipt_id:
            _assert_document_is_draft(self.purchase_receipt, action="modify lines on")
        self.amount = self.received_qty * self.rate
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.purchase_receipt_id:
            _assert_document_is_draft(self.purchase_receipt, action="delete lines from")
        return super().delete(*args, **kwargs)

    def validate_for_submission(self):
        if self.received_qty <= 0:
            raise ValidationError(f"Received quantity for {self.item.item_name} must be greater than zero.")
        if self.rate < 0:
            raise ValidationError(f"Rate for {self.item.item_name} cannot be negative.")
        if (
            self.item.disabled
            or self.item.has_variants
            or not self.item.is_stock_item
            or not self.item.is_purchase_item
        ):
            raise ValidationError(f"{self.item.item_name} is not an enabled stock and purchase item.")

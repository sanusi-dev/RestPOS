import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.settings.models import Branch
from apps.utils.models import BaseModel


class UOM(BaseModel):
    """Unit of measure (e.g. Nos, Kg, Litre, Box)."""

    name = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ItemGroup(BaseModel):
    """A node in the item classification tree (e.g. Food > Rice > Jollof)."""

    name = models.CharField(max_length=100, unique=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    is_group = models.BooleanField(default=False)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Warehouse(BaseModel):
    """A stock location within a branch (e.g. Main Store, Kitchen Store, Bar Store)."""

    name = models.CharField(max_length=100)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="warehouses")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    is_group = models.BooleanField(default=False)
    is_rejected = models.BooleanField(default=False)
    disabled = models.BooleanField(default=False)

    class Meta:
        unique_together = [("name", "branch")]
        ordering = ["branch__name", "name"]

    def __str__(self):
        return self.name


class Item(BaseModel):
    """A product or material tracked in inventory and sold via POS."""

    item_code = models.CharField(max_length=50, unique=True)
    item_name = models.CharField(max_length=200)
    item_group = models.ForeignKey(ItemGroup, on_delete=models.PROTECT, related_name="items")
    stock_uom = models.ForeignKey(UOM, on_delete=models.PROTECT, related_name="items")
    department = models.CharField(
        max_length=10,
        choices=[("FOOD", "Food"), ("DRINKS", "Drinks")],
    )
    image = models.ImageField(upload_to="items/", null=True, blank=True)
    description = models.TextField(blank=True)
    disabled = models.BooleanField(default=False)
    is_stock_item = models.BooleanField(default=True)
    default_warehouse = models.ForeignKey(
        Warehouse,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="default_items",
    )
    valuation_method = models.CharField(
        max_length=20,
        choices=[("FIFO", "FIFO"), ("MOVING_AVERAGE", "Moving Average")],
        default="FIFO",
    )
    has_batch_no = models.BooleanField(default=False)
    has_expiry_date = models.BooleanField(default=False)
    shelf_life_in_days = models.IntegerField(null=True, blank=True)
    has_variants = models.BooleanField(default=False)
    variant_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="variants",
    )
    safety_stock = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    lead_time_days = models.IntegerField(null=True, blank=True)
    end_of_life = models.DateField(null=True, blank=True)
    standard_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["item_name"]

    def __str__(self):
        return self.item_name or self.item_code

    def clean(self):
        super().clean()
        if self.has_variants and self.is_stock_item:
            raise ValidationError("Template items with variants cannot maintain stock")
        if self.variant_of_id and not self.variant_of.has_variants:
            raise ValidationError("Parent item must have has_variants=True")
        if self.has_expiry_date and not self.has_batch_no:
            raise ValidationError("Expiry date tracking requires batch tracking (has_batch_no=True)")
        if self.has_expiry_date and not self.shelf_life_in_days:
            raise ValidationError("Shelf life in days is required when expiry date tracking is enabled")


class ItemBarcode(BaseModel):
    """A barcode associated with an item (an item may have many barcodes)."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="barcodes")
    barcode = models.CharField(max_length=100, unique=True)
    barcode_type = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["barcode"]

    def __str__(self):
        return self.barcode


class ItemUOMConversion(BaseModel):
    """Conversion factor from the item's stock UOM to an alternate UOM."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="uom_conversions")
    uom = models.ForeignKey(UOM, on_delete=models.CASCADE)
    conversion_factor = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        unique_together = [("item", "uom")]

    def __str__(self):
        return f"{self.uom.name} (x{self.conversion_factor})"


class ReorderLevel(BaseModel):
    """Per-warehouse reorder level and quantity for an item."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="reorder_levels")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE)
    reorder_level = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    reorder_qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    class Meta:
        unique_together = [("item", "warehouse")]


class Batch(BaseModel):
    """A batch of a batch-tracked item, optionally with expiry."""

    batch_id = models.CharField(max_length=100, unique=True)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="batches")
    expiry_date = models.DateField(null=True, blank=True)
    manufacturing_date = models.DateField(null=True, blank=True)
    batch_qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"), editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.batch_id

    def clean(self):
        super().clean()
        if self.item_id and not self.item.has_batch_no:
            raise ValidationError("Item must have has_batch_no=True to use batch tracking")
        if (
            self.item_id
            and self.item.has_expiry_date
            and self.manufacturing_date
            and not self.expiry_date
            and self.item.shelf_life_in_days
        ):
            from datetime import timedelta

            self.expiry_date = self.manufacturing_date + timedelta(days=self.item.shelf_life_in_days)

    def recalculate_qty(self):
        """Recompute batch_qty from net stock ledger entries for this batch."""
        total = Decimal("0")
        for sle in self.item.stock_ledger_entries.filter(voucher_detail_no=self.batch_id):
            total += sle.actual_qty
        self.batch_qty = total
        self.save(update_fields=["batch_qty", "updated_at"])


class ProductBundle(BaseModel):
    """A bundle sold as a single item composed of multiple component items."""

    parent_item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="bundles")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("parent_item",)]

    def __str__(self):
        return self.parent_item.item_name


class ProductBundleItem(BaseModel):
    """A component line of a product bundle."""

    bundle = models.ForeignKey(ProductBundle, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.item.item_name} x{self.qty}"


class Bin(BaseModel):
    """The current stock snapshot for a single item in a single warehouse."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="bins")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="bins")
    actual_qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    reserved_qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    valuation_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    stock_value = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        unique_together = [("item", "warehouse")]

    def __str__(self):
        return f"{self.item.item_code} @ {self.warehouse.name}: {self.actual_qty}"

    @classmethod
    def get_or_create_bin(cls, item, warehouse):
        """Return the existing Bin for item+warehouse, or create a new one."""
        bin_obj, _created = cls.objects.get_or_create(item=item, warehouse=warehouse)
        return bin_obj

    def current_stock_queue(self):
        """Return the FIFO queue ([qty, rate] pairs) from the latest non-cancelled SLE."""
        latest = (
            StockLedgerEntry.objects.filter(item=self.item, warehouse=self.warehouse, is_cancelled=False)
            .order_by("-posting_datetime", "-pk")
            .first()
        )
        if latest and latest.stock_queue:
            try:
                raw = json.loads(latest.stock_queue)
                return [[Decimal(str(q)), Decimal(str(r))] for q, r in raw]
            except json.JSONDecodeError, TypeError:
                return []
        return []


class StockLedgerEntry(BaseModel):
    """An immutable record of a single stock movement for one item in one warehouse.

    This is the core of the inventory ledger — every stock change creates one
    or more SLE rows. Submitted documents are never edited; cancellation
    creates reversal entries.
    """

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="stock_ledger_entries")
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="stock_ledger_entries",
    )
    posting_datetime = models.DateTimeField(auto_now_add=True, editable=False)
    voucher_type = models.CharField(max_length=50)
    voucher_no = models.CharField(max_length=100)
    voucher_detail_no = models.CharField(max_length=100, blank=True)
    actual_qty = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    qty_after_transaction = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    incoming_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"), editable=False)
    outgoing_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"), editable=False)
    valuation_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"), editable=False)
    stock_value = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    stock_queue = models.TextField(blank=True, default="")
    is_cancelled = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["-posting_datetime"]
        indexes = [models.Index(fields=["item", "warehouse", "-posting_datetime"])]

    def __str__(self):
        sign = "+" if self.actual_qty >= 0 else ""
        return f"{sign}{self.actual_qty} {self.item.item_code} @ {self.warehouse.name}"

    @classmethod
    def create_entry(
        cls,
        item,
        warehouse,
        actual_qty,
        voucher_type,
        voucher_no,
        rate=Decimal("0"),
        voucher_detail_no="",
        batch=None,
    ):
        """Create a ledger entry and update the corresponding Bin.

        ``actual_qty`` is signed: positive for receipts, negative for issues.
        ``rate`` is the incoming rate (ignored for outgoing moves where FIFO
        or moving-average valuation supplies the outgoing rate).
        """
        bin_obj = Bin.get_or_create_bin(item, warehouse)
        current_qty = bin_obj.actual_qty or Decimal("0")
        current_rate = bin_obj.valuation_rate or Decimal("0")
        new_qty = current_qty + actual_qty

        incoming_rate = Decimal("0")
        outgoing_rate = Decimal("0")
        valuation_rate = current_rate

        # Maintain a FIFO queue of [qty, rate] pairs, read from the latest SLE.
        try:
            latest = (
                cls.objects.filter(item=item, warehouse=warehouse, is_cancelled=False)
                .order_by("-posting_datetime", "-pk")
                .first()
            )
            queue = (
                [[Decimal(str(q)), Decimal(str(r))] for q, r in json.loads(latest.stock_queue)]
                if latest and latest.stock_queue
                else []
            )
        except json.JSONDecodeError, TypeError:
            queue = []

        if actual_qty > 0:
            # Receipt — append to the back of the FIFO queue.
            incoming_rate = rate
            queue.append([actual_qty, rate])
            if item.valuation_method == "MOVING_AVERAGE":
                total_value = current_qty * current_rate + actual_qty * rate
                valuation_rate = (total_value / new_qty) if new_qty != 0 else Decimal("0")
            else:  # FIFO
                valuation_rate = rate
        elif actual_qty < 0:
            # Issue — consume from the queue to compute outgoing rate.
            if item.valuation_method == "MOVING_AVERAGE":
                # Moving average: outgoing rate is the current average; rate is unchanged after issue.
                outgoing_rate = current_rate
                valuation_rate = current_rate
                # Drain the queue proportionally so it stays consistent.
                remaining = abs(actual_qty)
                while remaining > 0 and queue:
                    front_qty, front_rate = queue[0]
                    if front_qty <= remaining:
                        remaining -= front_qty
                        queue.pop(0)
                    else:
                        queue[0] = [front_qty - remaining, front_rate]
                        remaining = Decimal("0")
            else:
                # FIFO: pop from the front of the queue to compute outgoing rate.
                remaining = abs(actual_qty)
                consumed_value = Decimal("0")
                while remaining > 0 and queue:
                    front_qty, front_rate = queue[0]
                    if front_qty <= remaining:
                        consumed_value += front_qty * front_rate
                        remaining -= front_qty
                        queue.pop(0)
                    else:
                        consumed_value += remaining * front_rate
                        queue[0] = [front_qty - remaining, front_rate]
                        remaining = Decimal("0")
                outgoing_rate = consumed_value / abs(actual_qty) if actual_qty != 0 else Decimal("0")
                # Valuation rate after issue is the weighted average of remaining queue.
                if queue:
                    remaining_qty = sum(q for q, _ in queue)
                    remaining_value = sum(q * r for q, r in queue)
                    valuation_rate = remaining_value / remaining_qty if remaining_qty != 0 else Decimal("0")
                else:
                    valuation_rate = Decimal("0")
        else:
            # Zero-qty adjustment (e.g. rate-only reconciliation) — no queue change.
            pass

        stock_value = new_qty * valuation_rate

        sle = cls.objects.create(
            item=item,
            warehouse=warehouse,
            actual_qty=actual_qty,
            qty_after_transaction=new_qty,
            incoming_rate=incoming_rate,
            outgoing_rate=outgoing_rate,
            valuation_rate=valuation_rate,
            stock_value=stock_value,
            stock_queue=json.dumps([[str(q), str(r)] for q, r in queue]),
            voucher_type=voucher_type,
            voucher_no=voucher_no,
            voucher_detail_no=voucher_detail_no,
        )

        bin_obj.actual_qty = new_qty
        bin_obj.valuation_rate = valuation_rate
        bin_obj.stock_value = stock_value
        bin_obj.save(
            update_fields=[
                "actual_qty",
                "reserved_qty",
                "valuation_rate",
                "stock_value",
                "updated_at",
            ]
        )

        if batch:
            batch.recalculate_qty()

        return sle


class StockEntry(BaseModel):
    """A stock movement document (receipt, issue, transfer, or repack)."""

    purpose = models.CharField(
        max_length=30,
        choices=[
            ("MATERIAL_RECEIPT", "Material Receipt"),
            ("MATERIAL_ISSUE", "Material Issue"),
            ("MATERIAL_TRANSFER", "Material Transfer"),
            ("REPACK", "Repack"),
        ],
    )
    posting_date = models.DateField(default=timezone.now)
    from_warehouse = models.ForeignKey(
        Warehouse,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outgoing_stock_entries",
    )
    to_warehouse = models.ForeignKey(
        Warehouse,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="incoming_stock_entries",
    )
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

    def clean(self):
        super().clean()
        if self.purpose == "MATERIAL_RECEIPT" and not self.to_warehouse:
            raise ValidationError({"to_warehouse": "Material Receipt requires a target warehouse."})
        if self.purpose == "MATERIAL_ISSUE" and not self.from_warehouse:
            raise ValidationError({"from_warehouse": "Material Issue requires a source warehouse."})
        if self.purpose in ("MATERIAL_TRANSFER", "REPACK"):
            if not self.from_warehouse:
                raise ValidationError({"from_warehouse": "This purpose requires a source warehouse."})
            if not self.to_warehouse:
                raise ValidationError({"to_warehouse": "This purpose requires a target warehouse."})

    def submit(self):
        """Post the stock entry: create SLEs for every detail line and mark submitted."""
        if self.status != "DRAFT":
            return
        for detail in self.items.all():
            source = detail.source_warehouse or self.from_warehouse
            target = detail.target_warehouse or self.to_warehouse
            rate = detail.basic_rate
            voucher_no = str(self.pk)

            if self.purpose == "MATERIAL_RECEIPT":
                StockLedgerEntry.create_entry(
                    item=detail.item,
                    warehouse=target,
                    actual_qty=detail.qty,
                    voucher_type="Stock Entry",
                    voucher_no=voucher_no,
                    rate=rate,
                    voucher_detail_no=str(detail.pk),
                    batch=detail.batch,
                )
            elif self.purpose == "MATERIAL_ISSUE":
                StockLedgerEntry.create_entry(
                    item=detail.item,
                    warehouse=source,
                    actual_qty=-detail.qty,
                    voucher_type="Stock Entry",
                    voucher_no=voucher_no,
                    voucher_detail_no=str(detail.pk),
                    batch=detail.batch,
                )
            elif self.purpose in ("MATERIAL_TRANSFER", "REPACK"):
                StockLedgerEntry.create_entry(
                    item=detail.item,
                    warehouse=source,
                    actual_qty=-detail.qty,
                    voucher_type="Stock Entry",
                    voucher_no=voucher_no,
                    rate=Decimal("0"),
                    voucher_detail_no=str(detail.pk),
                    batch=detail.batch,
                )
                StockLedgerEntry.create_entry(
                    item=detail.item,
                    warehouse=target,
                    actual_qty=detail.qty,
                    voucher_type="Stock Entry",
                    voucher_no=voucher_no,
                    rate=rate,
                    voucher_detail_no=str(detail.pk),
                    batch=detail.batch,
                )
        self.status = "SUBMITTED"
        self.save(update_fields=["status", "updated_at"])

    def cancel(self):
        """Reverse every SLE created by this entry and mark cancelled."""
        if self.status != "SUBMITTED":
            return
        voucher_no = str(self.pk)
        for sle in self.stock_ledger_entries_for_voucher(voucher_no):
            if sle.is_cancelled:
                continue
            StockLedgerEntry.create_entry(
                item=sle.item,
                warehouse=sle.warehouse,
                actual_qty=-sle.actual_qty,
                voucher_type="Stock Entry Cancellation",
                voucher_no=voucher_no,
                rate=sle.incoming_rate if sle.actual_qty > 0 else Decimal("0"),
                voucher_detail_no=sle.voucher_detail_no,
            )
            sle.is_cancelled = True
            sle.save(update_fields=["is_cancelled", "updated_at"])
        self.status = "CANCELLED"
        self.save(update_fields=["status", "updated_at"])

    @staticmethod
    def stock_ledger_entries_for_voucher(voucher_no):
        return StockLedgerEntry.objects.filter(voucher_type="Stock Entry", voucher_no=voucher_no)


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
    uom = models.ForeignKey(UOM, on_delete=models.PROTECT)
    conversion_factor = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1"))
    basic_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.item.item_code} x{self.qty}"


class StockReconciliation(BaseModel):
    """A document that adjusts stock to match a physical count."""

    purpose = models.CharField(
        max_length=20,
        choices=[("OPENING_STOCK", "Opening Stock"), ("RECONCILIATION", "Stock Reconciliation")],
        default="RECONCILIATION",
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

    def submit(self):
        """Post adjustment SLEs so each item's Bin matches the counted qty."""
        if self.status != "DRAFT":
            return
        voucher_no = str(self.pk)
        for line in self.items.all():
            current_qty = line.current_qty
            difference = line.qty - current_qty
            if difference == 0:
                continue
            rate = line.valuation_rate or Decimal("0")
            StockLedgerEntry.create_entry(
                item=line.item,
                warehouse=line.warehouse,
                actual_qty=difference,
                voucher_type="Stock Reconciliation",
                voucher_no=voucher_no,
                rate=rate,
                voucher_detail_no=str(line.pk),
            )
        self.status = "SUBMITTED"
        self.save(update_fields=["status", "updated_at"])

    def cancel(self):
        """Reverse every SLE created by this reconciliation and mark cancelled."""
        if self.status != "SUBMITTED":
            return
        voucher_no = str(self.pk)
        for sle in StockLedgerEntry.objects.filter(voucher_type="Stock Reconciliation", voucher_no=voucher_no):
            if sle.is_cancelled:
                continue
            StockLedgerEntry.create_entry(
                item=sle.item,
                warehouse=sle.warehouse,
                actual_qty=-sle.actual_qty,
                voucher_type="Stock Reconciliation Cancellation",
                voucher_no=voucher_no,
                rate=sle.incoming_rate if sle.actual_qty > 0 else Decimal("0"),
                voucher_detail_no=sle.voucher_detail_no,
            )
            sle.is_cancelled = True
            sle.save(update_fields=["is_cancelled", "updated_at"])
        self.status = "CANCELLED"
        self.save(update_fields=["status", "updated_at"])


class StockReconciliationItem(BaseModel):
    """A single line item of a stock reconciliation (one item's counted qty)."""

    reconciliation = models.ForeignKey(
        StockReconciliation,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
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
        if not self.pk and self.item_id and self.warehouse_id:
            bin_obj = Bin.get_or_create_bin(self.item, self.warehouse)
            self.current_qty = bin_obj.actual_qty
        super().save(*args, **kwargs)


class PurchaseReceipt(BaseModel):
    """Records the receipt of goods from a supplier (FEATURES.md #123).

    When a delivery arrives the storekeeper creates a purchase receipt listing
    items, quantities and rates. On submit it increases stock levels (via Stock
    Ledger Entries) and records an implicit liability to the supplier. Damaged
    items may be routed to a rejected warehouse instead of the main warehouse.
    """

    supplier_name = models.CharField(max_length=200)
    supplier_delivery_note = models.CharField(max_length=100, blank=True)
    posting_date = models.DateField(default=timezone.now)
    accepted_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="purchase_receipts",
    )
    rejected_warehouse = models.ForeignKey(
        Warehouse,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="rejected_receipts",
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

    def clean(self):
        super().clean()
        if not self.accepted_warehouse_id:
            raise ValidationError({"accepted_warehouse": "Accepted warehouse is required."})

    def submit(self):
        """Post the receipt: create SLEs for accepted and rejected quantities."""
        if self.status != "DRAFT":
            return
        voucher_no = str(self.pk)
        total = Decimal("0")
        for line in self.items.all():
            target = line.warehouse or self.accepted_warehouse
            if line.accepted_qty > 0:
                StockLedgerEntry.create_entry(
                    item=line.item,
                    warehouse=target,
                    actual_qty=line.accepted_qty,
                    voucher_type="Purchase Receipt",
                    voucher_no=voucher_no,
                    rate=line.rate,
                    voucher_detail_no=str(line.pk),
                    batch=line.batch,
                )
            if line.rejected_qty > 0 and self.rejected_warehouse_id:
                StockLedgerEntry.create_entry(
                    item=line.item,
                    warehouse=self.rejected_warehouse,
                    actual_qty=line.rejected_qty,
                    voucher_type="Purchase Receipt",
                    voucher_no=voucher_no,
                    rate=line.rate,
                    voucher_detail_no=str(line.pk),
                    batch=line.batch,
                )
            total += line.amount
        self.total = total
        self.status = "SUBMITTED"
        self.save(update_fields=["status", "total", "updated_at"])

    def cancel(self):
        """Reverse every SLE created by this receipt and mark cancelled."""
        if self.status != "SUBMITTED":
            return
        voucher_no = str(self.pk)
        for sle in StockLedgerEntry.objects.filter(voucher_type="Purchase Receipt", voucher_no=voucher_no):
            if sle.is_cancelled:
                continue
            StockLedgerEntry.create_entry(
                item=sle.item,
                warehouse=sle.warehouse,
                actual_qty=-sle.actual_qty,
                voucher_type="Purchase Receipt Cancellation",
                voucher_no=voucher_no,
                rate=sle.incoming_rate if sle.actual_qty > 0 else Decimal("0"),
                voucher_detail_no=sle.voucher_detail_no,
            )
            sle.is_cancelled = True
            sle.save(update_fields=["is_cancelled", "updated_at"])
        self.status = "CANCELLED"
        self.save(update_fields=["status", "updated_at"])


class PurchaseReceiptItem(BaseModel):
    """A single line item of a purchase receipt."""

    purchase_receipt = models.ForeignKey(
        PurchaseReceipt,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="purchase_receipt_items")
    received_qty = models.DecimalField(max_digits=10, decimal_places=2)
    rejected_qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    accepted_qty = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        editable=False,
    )
    uom = models.ForeignKey(UOM, on_delete=models.PROTECT)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(
        Warehouse,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="purchase_receipt_item_warehouses",
    )

    def __str__(self):
        return f"{self.item.item_code} x{self.received_qty}"

    def save(self, *args, **kwargs):
        self.accepted_qty = self.received_qty - self.rejected_qty
        self.amount = self.received_qty * self.rate
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.rejected_qty > self.received_qty:
            raise ValidationError("rejected_qty cannot exceed received_qty")

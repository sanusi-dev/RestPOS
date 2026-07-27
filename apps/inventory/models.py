import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.settings.models import Branch
from apps.utils.models import BaseModel


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

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Warehouse(BaseModel):
    """A stock location (e.g. Main Store, Kitchen Store, Bar Store).

    Phase 1: branch is implicit (Branch.get_default()); not user-selected in UI.
    """

    name = models.CharField(max_length=100)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="warehouses")
    disabled = models.BooleanField(default=False)

    class Meta:
        unique_together = [("name", "branch")]
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.branch_id:
            default_branch = Branch.get_default()
            if default_branch is None:
                raise ValidationError({"branch": "Create a branch in Settings before creating a warehouse."})
            self.branch = default_branch
        super().save(*args, **kwargs)


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
    image = models.ImageField(upload_to="items/", null=True, blank=True)
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

    @classmethod
    def get_or_create_bin_id(cls, item_id, warehouse_id):
        """Same as get_or_create_bin but takes ids directly — skips FK instance loads."""
        bin_obj, _created = cls.objects.get_or_create(item_id=item_id, warehouse_id=warehouse_id)
        return bin_obj

    def current_stock_queue(self):
        """Return the FIFO queue ([qty, rate] pairs) from the latest non-cancelled SLE."""
        # Filter by ids so this is safe to call on a Bin whose FKs weren't loaded.
        latest = (
            StockLedgerEntry.objects.filter(item_id=self.item_id, warehouse_id=self.warehouse_id, is_cancelled=False)
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
            incoming_rate = rate
            queue.append([actual_qty, rate])
            valuation_rate = rate
        elif actual_qty < 0:
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

        return sle


class StockEntry(BaseModel):
    """A stock movement document (receipt, issue, transfer, or repack)."""

    purpose = models.CharField(
        max_length=30,
        choices=[
            ("MATERIAL_RECEIPT", "Material Receipt"),
            ("MATERIAL_ISSUE", "Material Issue"),
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

    def submit(self):
        """Post the stock entry: create SLEs for every detail line and mark submitted."""
        if self.status != "DRAFT":
            return
        voucher_no = str(self.pk)
        updated_items = set()
        for detail in self.items.select_related("item", "source_warehouse", "target_warehouse").all():
            source = detail.source_warehouse
            target = detail.target_warehouse
            rate = detail.basic_rate

            if self.purpose == "MATERIAL_RECEIPT":
                StockLedgerEntry.create_entry(
                    item=detail.item,
                    warehouse=target,
                    actual_qty=detail.qty,
                    voucher_type="Stock Entry",
                    voucher_no=voucher_no,
                    rate=rate,
                    voucher_detail_no=str(detail.pk),
                )
                detail.item.last_purchase_rate = rate
                updated_items.add(detail.item)
            elif self.purpose == "MATERIAL_ISSUE":
                StockLedgerEntry.create_entry(
                    item=detail.item,
                    warehouse=source,
                    actual_qty=-detail.qty,
                    voucher_type="Stock Entry",
                    voucher_no=voucher_no,
                    voucher_detail_no=str(detail.pk),
                )
            elif self.purpose == "MATERIAL_TRANSFER":
                StockLedgerEntry.create_entry(
                    item=detail.item,
                    warehouse=source,
                    actual_qty=-detail.qty,
                    voucher_type="Stock Entry",
                    voucher_no=voucher_no,
                    rate=Decimal("0"),
                    voucher_detail_no=str(detail.pk),
                )
                StockLedgerEntry.create_entry(
                    item=detail.item,
                    warehouse=target,
                    actual_qty=detail.qty,
                    voucher_type="Stock Entry",
                    voucher_no=voucher_no,
                    rate=rate,
                    voucher_detail_no=str(detail.pk),
                )
        if updated_items:
            Item.objects.bulk_update(updated_items, ["last_purchase_rate", "updated_at"])
        self.status = "SUBMITTED"
        self.save(update_fields=["status", "updated_at"])

    def cancel(self):
        """Reverse every SLE created by this entry and mark cancelled."""
        if self.status != "SUBMITTED":
            return
        voucher_no = str(self.pk)
        # Exclude already-cancelled rows upfront so the loop body runs once per real SLE.
        for sle in self.stock_ledger_entries_for_voucher(voucher_no).exclude(is_cancelled=True):
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

    def clean(self):
        super().clean()
        if not self.stock_entry_id:
            return
        purpose = self.stock_entry.purpose
        if purpose == "MATERIAL_RECEIPT":
            if not self.target_warehouse_id:
                raise ValidationError({"target_warehouse": "Material Receipt requires a target warehouse."})
            if self.source_warehouse_id:
                raise ValidationError({"source_warehouse": "Material Receipt should not have a source warehouse."})
        elif purpose == "MATERIAL_ISSUE":
            if not self.source_warehouse_id:
                raise ValidationError({"source_warehouse": "Material Issue requires a source warehouse."})
            if self.target_warehouse_id:
                raise ValidationError({"target_warehouse": "Material Issue should not have a target warehouse."})
        elif purpose == "MATERIAL_TRANSFER":
            if not self.source_warehouse_id:
                raise ValidationError({"source_warehouse": "Material Transfer requires a source warehouse."})
            if not self.target_warehouse_id:
                raise ValidationError({"target_warehouse": "Material Transfer requires a target warehouse."})


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
        for line in self.items.select_related("item", "warehouse").all():
            current_qty = line.current_qty
            difference = line.qty - current_qty
            if difference == 0:
                continue
            rate = line.valuation_rate if self.purpose == "OPENING_STOCK" else Decimal("0")
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
        sles = (
            StockLedgerEntry.objects.filter(voucher_type="Stock Reconciliation", voucher_no=voucher_no)
            .select_related("item", "warehouse")
            .exclude(is_cancelled=True)
        )
        for sle in sles:
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
            # Pass ids, not FK instances — avoids two FK fetches per line on a formset save.
            bin_obj = Bin.get_or_create_bin_id(self.item_id, self.warehouse_id)
            self.current_qty = bin_obj.actual_qty
        super().save(*args, **kwargs)


class PurchaseReceipt(BaseModel):
    """Records the receipt of goods from a supplier (FEATURES.md #123).

    When a delivery arrives the storekeeper creates a purchase receipt listing
    items, quantities and rates. On submit it increases stock in the receipt's
    warehouse (via Stock Ledger Entries). The whole receipt goes to one store
    room — further movement (e.g. store → kitchen) is done with Stock Entry.
    Only quantities that enter stock are recorded; damaged/refused goods are
    omitted (or written off later via Stock Reconciliation / Material Issue).
    """

    supplier_name = models.CharField(max_length=200)
    supplier_delivery_note = models.CharField(max_length=100, blank=True)
    posting_date = models.DateField(default=timezone.now)
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="purchase_receipts",
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
        if not self.warehouse_id:
            raise ValidationError({"warehouse": "Warehouse is required."})

    def submit(self):
        """Post the receipt: create SLEs for each line into self.warehouse."""
        if self.status != "DRAFT":
            return
        voucher_no = str(self.pk)
        total = Decimal("0")
        updated_items = set()
        for line in self.items.select_related("item").all():
            if line.received_qty > 0:
                StockLedgerEntry.create_entry(
                    item=line.item,
                    warehouse=self.warehouse,
                    actual_qty=line.received_qty,
                    voucher_type="Purchase Receipt",
                    voucher_no=voucher_no,
                    rate=line.rate,
                    voucher_detail_no=str(line.pk),
                )
            line.item.last_purchase_rate = line.rate
            updated_items.add(line.item)
            total += line.amount
        Item.objects.bulk_update(updated_items, ["last_purchase_rate", "updated_at"])
        self.total = total
        self.status = "SUBMITTED"
        self.save(update_fields=["status", "total", "updated_at"])

    def cancel(self):
        """Reverse every SLE created by this receipt and mark cancelled."""
        if self.status != "SUBMITTED":
            return
        voucher_no = str(self.pk)
        sles = (
            StockLedgerEntry.objects.filter(voucher_type="Purchase Receipt", voucher_no=voucher_no)
            .select_related("item", "warehouse")
            .exclude(is_cancelled=True)
        )
        for sle in sles:
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
        self._revert_last_purchase_rates()
        self.status = "CANCELLED"
        self.save(update_fields=["status", "updated_at"])

    def _revert_last_purchase_rates(self):
        # select_related("item") avoids per-line FK fetch. We keep the per-line prior-rate
        # lookup (FIFO queue tail is intentionally per item) but combine the writes into
        # a single bulk_update at the end instead of one UPDATE per line.
        lines = list(self.items.select_related("item").all())
        if not lines:
            return
        items_to_update = []
        for line in lines:
            prior = (
                PurchaseReceiptItem.objects.filter(
                    item=line.item,
                    purchase_receipt__status="SUBMITTED",
                )
                .exclude(purchase_receipt=self)
                .select_related("purchase_receipt")
                .order_by("-purchase_receipt__posting_date", "-purchase_receipt__pk")
                .first()
            )
            line.item.last_purchase_rate = prior.rate if prior else None
            items_to_update.append(line.item)
        Item.objects.bulk_update(items_to_update, ["last_purchase_rate", "updated_at"])


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
        self.amount = self.received_qty * self.rate
        super().save(*args, **kwargs)

import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.utils.models import BaseModel


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

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Warehouse(BaseModel):
    """A stock location (e.g. Main Store, Kitchen Store, Bar Store)."""

    name = models.CharField(max_length=100, unique=True)
    disabled = models.BooleanField(default=False)

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
        prevent_negative=False,
    ):
        """Create a ledger entry and update the corresponding Bin.

        ``actual_qty`` is signed: positive for receipts, negative for issues.
        ``rate`` is the incoming rate (ignored for outgoing moves where FIFO
        or moving-average valuation supplies the outgoing rate).
        """
        with transaction.atomic():
            bin_obj = Bin.get_or_create_bin(item, warehouse)
            bin_obj = Bin.objects.select_for_update().get(pk=bin_obj.pk)
            return cls._create_entry_locked(
                item=item,
                warehouse=warehouse,
                actual_qty=actual_qty,
                voucher_type=voucher_type,
                voucher_no=voucher_no,
                rate=rate,
                voucher_detail_no=voucher_detail_no,
                prevent_negative=prevent_negative,
                bin_obj=bin_obj,
            )

    @classmethod
    def _create_entry_locked(
        cls,
        *,
        item,
        warehouse,
        actual_qty,
        voucher_type,
        voucher_no,
        rate,
        voucher_detail_no,
        prevent_negative,
        bin_obj,
    ):
        current_qty = bin_obj.actual_qty or Decimal("0")
        current_rate = bin_obj.valuation_rate or Decimal("0")
        new_qty = current_qty + actual_qty
        if prevent_negative and new_qty < 0:
            raise ValidationError(f"Insufficient stock for {item.item_name} in {warehouse.name}.")

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
            # FIFO: consume the oldest [qty, rate] batches first. The consumed
            # value sets the outgoing rate; what remains becomes the new queue
            # and its weighted-average rate the new valuation rate.
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

        # The Bin mirrors the ledger's tail state so reads don't need to
        # replay the SLE history.
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

    def submit(self):
        """Post the stock entry: create SLEs for every detail line and mark submitted."""
        from apps.settings.models import ProductionUnit, Restaurant

        with transaction.atomic():
            entry = StockEntry.objects.select_for_update().get(pk=self.pk)
            if entry.status != "DRAFT":
                self.status = entry.status
                return
            restaurant = Restaurant.load()
            if not restaurant or not restaurant.store_warehouse_id or restaurant.store_warehouse.disabled:
                raise ValidationError("Configure an enabled central Store warehouse before submitting.")
            if entry.purpose not in {"MATERIAL_RECEIPT", "MATERIAL_TRANSFER"}:
                raise ValidationError("Unsupported stock entry purpose.")

            targets = {}
            if entry.purpose == "MATERIAL_TRANSFER":
                # Store is the only source; FOOD flows to the Kitchen unit's
                # warehouse and DRINKS to the Bar / POS sales warehouse.
                if not restaurant.default_warehouse_id or restaurant.default_warehouse.disabled:
                    raise ValidationError("Configure an enabled Bar / POS sales warehouse before transferring stock.")
                units = {
                    unit.department: unit
                    for unit in ProductionUnit.objects.select_related("warehouse").filter(
                        department__in=[ProductionUnit.FOOD, ProductionUnit.DRINKS]
                    )
                }
                food_unit = units.get(ProductionUnit.FOOD)
                drinks_unit = units.get(ProductionUnit.DRINKS)
                if not food_unit or food_unit.warehouse.disabled:
                    raise ValidationError(
                        "Configure an enabled Kitchen production unit warehouse before transferring stock."
                    )
                if (
                    not drinks_unit
                    or drinks_unit.warehouse.disabled
                    or drinks_unit.warehouse_id != restaurant.default_warehouse_id
                ):
                    raise ValidationError(
                        "Configure the Drinks production unit to use the enabled Bar / POS sales warehouse."
                    )
                if (
                    restaurant.store_warehouse_id
                    in {
                        restaurant.default_warehouse_id,
                        food_unit.warehouse_id,
                    }
                    or restaurant.default_warehouse_id == food_unit.warehouse_id
                ):
                    raise ValidationError("Store, Kitchen, and Bar warehouses must be distinct.")
                targets = {"FOOD": food_unit.warehouse, "DRINKS": restaurant.default_warehouse}

            details = list(entry.items.select_related("item", "source_warehouse", "target_warehouse"))
            if not details:
                raise ValidationError("Add at least one item before submitting.")
            for detail in details:
                detail.validate_for_submission(restaurant=restaurant, targets=targets)

            bin_keys = {
                (detail.item_id, warehouse_id)
                for detail in details
                for warehouse_id in (
                    [restaurant.store_warehouse_id]
                    if entry.purpose == "MATERIAL_RECEIPT"
                    else [restaurant.store_warehouse_id, targets[detail.item.department].pk]
                )
            }
            for item_id, warehouse_id in sorted(bin_keys):
                Bin.get_or_create_bin_id(item_id, warehouse_id)
            # Stable lock ordering prevents two multi-line documents from
            # deadlocking while they update FIFO state for shared bins.
            locked_bins = {
                (bin_obj.item_id, bin_obj.warehouse_id): bin_obj
                for bin_obj in Bin.objects.select_for_update()
                .filter(
                    item_id__in=[item_id for item_id, _ in bin_keys],
                    warehouse_id__in=[warehouse_id for _, warehouse_id in bin_keys],
                )
                .order_by("item_id", "warehouse_id")
            }

            voucher_no = str(entry.pk)
            updated_items = set()
            for detail in details:
                store_bin = locked_bins[(detail.item_id, restaurant.store_warehouse_id)]
                if entry.purpose == "MATERIAL_RECEIPT":
                    detail.source_warehouse = None
                    detail.target_warehouse = restaurant.store_warehouse
                    StockLedgerEntry._create_entry_locked(
                        item=detail.item,
                        warehouse=restaurant.store_warehouse,
                        actual_qty=detail.qty,
                        voucher_type="Stock Entry",
                        voucher_no=voucher_no,
                        rate=detail.basic_rate,
                        voucher_detail_no=str(detail.pk),
                        prevent_negative=False,
                        bin_obj=store_bin,
                    )
                    # Receipts carry the purchase rate into the item's last-buy
                    # price so downstream transfers are valued at cost.
                    detail.item.last_purchase_rate = detail.basic_rate
                    updated_items.add(detail.item)
                else:
                    target = targets[detail.item.department]
                    detail.source_warehouse = restaurant.store_warehouse
                    detail.target_warehouse = target
                    outgoing = StockLedgerEntry._create_entry_locked(
                        item=detail.item,
                        warehouse=restaurant.store_warehouse,
                        actual_qty=-detail.qty,
                        voucher_type="Stock Entry",
                        voucher_no=voucher_no,
                        rate=Decimal("0"),
                        voucher_detail_no=str(detail.pk),
                        prevent_negative=True,
                        bin_obj=store_bin,
                    )
                    # The transfer-in is valued at the outgoing FIFO rate so
                    # the store's cost follows the goods into the unit.
                    StockLedgerEntry._create_entry_locked(
                        item=detail.item,
                        warehouse=target,
                        actual_qty=detail.qty,
                        voucher_type="Stock Entry",
                        voucher_no=voucher_no,
                        rate=outgoing.outgoing_rate,
                        voucher_detail_no=str(detail.pk),
                        prevent_negative=False,
                        bin_obj=locked_bins[(detail.item_id, target.pk)],
                    )
                detail.save(update_fields=["source_warehouse", "target_warehouse", "updated_at"])
            if updated_items:
                Item.objects.bulk_update(updated_items, ["last_purchase_rate", "updated_at"])
            entry.status = "SUBMITTED"
            entry.save(update_fields=["status", "updated_at"])
            self.status = entry.status

    def cancel(self):
        """Reverse every SLE created by this entry and mark cancelled."""
        with transaction.atomic():
            entry = StockEntry.objects.select_for_update().get(pk=self.pk)
            if entry.status != "SUBMITTED":
                self.status = entry.status
                return
            voucher_no = str(entry.pk)
            sles = list(
                self.stock_ledger_entries_for_voucher(voucher_no).select_for_update().exclude(is_cancelled=True)
            )
            bin_keys = {(sle.item_id, sle.warehouse_id) for sle in sles}
            locked_bins = {
                (bin_obj.item_id, bin_obj.warehouse_id): bin_obj
                for bin_obj in Bin.objects.select_for_update()
                .filter(
                    item_id__in=[item_id for item_id, _ in bin_keys],
                    warehouse_id__in=[warehouse_id for _, warehouse_id in bin_keys],
                )
                .order_by("item_id", "warehouse_id")
            }
            for sle in sles:
                StockLedgerEntry._create_entry_locked(
                    item=sle.item,
                    warehouse=sle.warehouse,
                    actual_qty=-sle.actual_qty,
                    voucher_type="Stock Entry Cancellation",
                    voucher_no=voucher_no,
                    rate=sle.outgoing_rate if sle.actual_qty < 0 else Decimal("0"),
                    voucher_detail_no=sle.voucher_detail_no,
                    prevent_negative=sle.actual_qty > 0,
                    bin_obj=locked_bins[(sle.item_id, sle.warehouse_id)],
                )
                sle.is_cancelled = True
                sle.save(update_fields=["is_cancelled", "updated_at"])
            entry.status = "CANCELLED"
            entry.save(update_fields=["status", "updated_at"])
            self.status = entry.status

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

    def submit(self):
        """Post adjustment SLEs so each item's Bin matches the counted qty."""
        from apps.settings.models import ProductionUnit

        with transaction.atomic():
            reconciliation = StockReconciliation.objects.select_for_update().select_related("warehouse").get(pk=self.pk)
            if reconciliation.status != "DRAFT":
                self.status = reconciliation.status
                return
            if reconciliation.warehouse.disabled:
                raise ValidationError("The reconciliation warehouse must be enabled.")
            valid_reasons = {value for value, _label in reconciliation._meta.get_field("reason").choices}
            if reconciliation.reason not in valid_reasons:
                raise ValidationError("A reconciliation reason is required.")

            lines = list(reconciliation.items.select_related("item"))
            if not lines:
                raise ValidationError("Add at least one item before submitting.")
            for line in lines:
                if line.item.disabled or not line.item.is_stock_item or line.item.has_variants:
                    raise ValidationError(f"{line.item.item_name} is not an enabled stock item.")
                if line.qty < 0:
                    raise ValidationError(f"Counted quantity for {line.item.item_name} cannot be negative.")
            if reconciliation.reason == "CONSUMPTION":
                # Consumption write-offs only make sense at the Kitchen
                # warehouse: that's where food stock is used up in cooking.
                kitchen = (
                    ProductionUnit.objects.select_related("warehouse").filter(department=ProductionUnit.FOOD).first()
                )
                if not kitchen or kitchen.warehouse_id != reconciliation.warehouse_id:
                    raise ValidationError(
                        "Consumption reconciliation is only allowed for the configured Kitchen warehouse."
                    )
                if any(line.item.department != "FOOD" for line in lines):
                    raise ValidationError("Consumption reconciliation accepts FOOD stock items only.")

            for line in lines:
                Bin.get_or_create_bin_id(line.item_id, reconciliation.warehouse_id)
            locked_bins = {
                bin_obj.item_id: bin_obj
                for bin_obj in Bin.objects.select_for_update()
                .filter(item_id__in=[line.item_id for line in lines], warehouse_id=reconciliation.warehouse_id)
                .order_by("item_id")
            }
            voucher_no = str(reconciliation.pk)
            for line in lines:
                bin_obj = locked_bins[line.item_id]
                current_qty = bin_obj.actual_qty
                if reconciliation.purpose != "OPENING_STOCK" and line.qty < bin_obj.reserved_qty:
                    # A physical count can never dip below what the POS has
                    # promised to sell (open draft reservations).
                    raise ValidationError(
                        f"Counted quantity for {line.item.item_name} cannot be below reserved quantity "
                        f"({bin_obj.reserved_qty})."
                    )
                line.current_qty = current_qty
                line.save(update_fields=["current_qty", "updated_at"])
                difference = line.qty - current_qty
                if difference == 0:
                    continue
                # Opening stock values the item at its configured rate; a
                # reconciliation posts at zero and relies on the existing
                # FIFO valuation.
                rate = line.valuation_rate if reconciliation.purpose == "OPENING_STOCK" else Decimal("0")
                StockLedgerEntry._create_entry_locked(
                    item=line.item,
                    warehouse=reconciliation.warehouse,
                    actual_qty=difference,
                    voucher_type="Stock Reconciliation",
                    voucher_no=voucher_no,
                    rate=rate or Decimal("0"),
                    voucher_detail_no=str(line.pk),
                    prevent_negative=False,
                    bin_obj=bin_obj,
                )
            reconciliation.status = "SUBMITTED"
            reconciliation.save(update_fields=["status", "updated_at"])
            self.status = reconciliation.status

    def cancel(self):
        """Reverse every SLE created by this reconciliation and mark cancelled."""
        with transaction.atomic():
            reconciliation = StockReconciliation.objects.select_for_update().get(pk=self.pk)
            if reconciliation.status != "SUBMITTED":
                self.status = reconciliation.status
                return
            voucher_no = str(reconciliation.pk)
            sles = list(
                StockLedgerEntry.objects.select_for_update()
                .filter(voucher_type="Stock Reconciliation", voucher_no=voucher_no)
                .select_related("item", "warehouse")
                .exclude(is_cancelled=True)
            )
            bin_keys = {(sle.item_id, sle.warehouse_id) for sle in sles}
            locked_bins = {
                (bin_obj.item_id, bin_obj.warehouse_id): bin_obj
                for bin_obj in Bin.objects.select_for_update()
                .filter(
                    item_id__in=[item_id for item_id, _ in bin_keys],
                    warehouse_id__in=[warehouse_id for _, warehouse_id in bin_keys],
                )
                .order_by("item_id", "warehouse_id")
            }
            for sle in sles:
                StockLedgerEntry._create_entry_locked(
                    item=sle.item,
                    warehouse=sle.warehouse,
                    actual_qty=-sle.actual_qty,
                    voucher_type="Stock Reconciliation Cancellation",
                    voucher_no=voucher_no,
                    rate=sle.outgoing_rate if sle.actual_qty < 0 else Decimal("0"),
                    voucher_detail_no=sle.voucher_detail_no,
                    prevent_negative=sle.actual_qty > 0,
                    bin_obj=locked_bins[(sle.item_id, sle.warehouse_id)],
                )
                sle.is_cancelled = True
                sle.save(update_fields=["is_cancelled", "updated_at"])
            reconciliation.status = "CANCELLED"
            reconciliation.save(update_fields=["status", "updated_at"])
            self.status = reconciliation.status


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

    def submit(self):
        """Post the receipt: create SLEs for each line into self.warehouse."""
        from apps.settings.models import Restaurant

        with transaction.atomic():
            receipt = PurchaseReceipt.objects.select_for_update().get(pk=self.pk)
            if receipt.status != "DRAFT":
                self.status = receipt.status
                return
            restaurant = Restaurant.load()
            if not restaurant or not restaurant.store_warehouse_id or restaurant.store_warehouse.disabled:
                raise ValidationError("Configure an enabled central Store warehouse before submitting.")
            if receipt.warehouse_id and receipt.warehouse_id != restaurant.store_warehouse_id:
                raise ValidationError("Purchase Receipt warehouse must be the configured central Store.")

            lines = list(receipt.items.select_related("item"))
            if not lines:
                raise ValidationError("Add at least one item before submitting.")
            for line in lines:
                line.validate_for_submission()
                Bin.get_or_create_bin_id(line.item_id, restaurant.store_warehouse_id)
            locked_bins = {
                bin_obj.item_id: bin_obj
                for bin_obj in Bin.objects.select_for_update()
                .filter(item_id__in=[line.item_id for line in lines], warehouse_id=restaurant.store_warehouse_id)
                .order_by("item_id")
            }
            total = Decimal("0")
            updated_items = set()
            for line in lines:
                StockLedgerEntry._create_entry_locked(
                    item=line.item,
                    warehouse=restaurant.store_warehouse,
                    actual_qty=line.received_qty,
                    voucher_type="Purchase Receipt",
                    voucher_no=str(receipt.pk),
                    rate=line.rate,
                    voucher_detail_no=str(line.pk),
                    prevent_negative=False,
                    bin_obj=locked_bins[line.item_id],
                )
                line.item.last_purchase_rate = line.rate
                updated_items.add(line.item)
                total += line.amount
            Item.objects.bulk_update(updated_items, ["last_purchase_rate", "updated_at"])
            receipt.warehouse = restaurant.store_warehouse
            receipt.total = total
            receipt.status = "SUBMITTED"
            receipt.save(update_fields=["warehouse", "status", "total", "updated_at"])
            self.warehouse = receipt.warehouse
            self.total = receipt.total
            self.status = receipt.status

    def cancel(self):
        """Reverse every SLE created by this receipt and mark cancelled."""
        with transaction.atomic():
            receipt = PurchaseReceipt.objects.select_for_update().get(pk=self.pk)
            if receipt.status != "SUBMITTED":
                self.status = receipt.status
                return
            voucher_no = str(receipt.pk)
            sles = list(
                StockLedgerEntry.objects.select_for_update()
                .filter(voucher_type="Purchase Receipt", voucher_no=voucher_no, is_cancelled=False)
                .select_related("item", "warehouse")
                .order_by("item_id", "warehouse_id", "pk")
            )
            bin_keys = {(sle.item_id, sle.warehouse_id) for sle in sles}
            locked_bins = {
                (bin_obj.item_id, bin_obj.warehouse_id): bin_obj
                for bin_obj in Bin.objects.select_for_update()
                .filter(
                    item_id__in=[item_id for item_id, _ in bin_keys],
                    warehouse_id__in=[warehouse_id for _, warehouse_id in bin_keys],
                )
                .order_by("item_id", "warehouse_id")
            }
            for sle in sles:
                StockLedgerEntry._create_entry_locked(
                    item=sle.item,
                    warehouse=sle.warehouse,
                    actual_qty=-sle.actual_qty,
                    voucher_type="Purchase Receipt Cancellation",
                    voucher_no=voucher_no,
                    rate=Decimal("0"),
                    voucher_detail_no=sle.voucher_detail_no,
                    prevent_negative=sle.actual_qty > 0,
                    bin_obj=locked_bins[(sle.item_id, sle.warehouse_id)],
                )
                sle.is_cancelled = True
                sle.save(update_fields=["is_cancelled", "updated_at"])
            receipt._revert_last_purchase_rates()
            receipt.status = "CANCELLED"
            receipt.save(update_fields=["status", "updated_at"])
            self.status = receipt.status

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

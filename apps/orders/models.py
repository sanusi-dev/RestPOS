from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.inventory.models import Item, StockLedgerEntry
from apps.payments.models import ModeOfPayment
from apps.utils.models import BaseModel

DRAFT = "DRAFT"
SUBMITTED = "SUBMITTED"
CANCELLED = "CANCELLED"
STATUS_CHOICES = [(DRAFT, "Draft"), (SUBMITTED, "Submitted"), (CANCELLED, "Cancelled")]

DINE_IN = "DINE_IN"
TAKE_AWAY = "TAKE_AWAY"
ORDER_TYPE_CHOICES = [
    (DINE_IN, "Dine In"),
    (TAKE_AWAY, "Take Away"),
]

NEW_ORDER = "New Order"
ORDER_MODIFIED = "Order Modified"
KOT_CANCELLED = "Cancelled"
PARTIALLY_CANCELLED = "Partially Cancelled"
KOT_TYPE_CHOICES = [
    (NEW_ORDER, "New Order"),
    (ORDER_MODIFIED, "Order Modified"),
    (KOT_CANCELLED, "Cancelled"),
    (PARTIALLY_CANCELLED, "Partially Cancelled"),
]

TWO_PLACES = Decimal("0.01")


class Order(BaseModel):
    """A POS order — the single source of truth for items, payments, and status."""

    invoice_number = models.CharField(max_length=50, unique=True, null=True, blank=True, editable=False)
    order_number = models.PositiveIntegerField(null=True, blank=True, editable=False)
    order_type = models.CharField(max_length=20, choices=ORDER_TYPE_CHOICES, default=DINE_IN)
    customer_name = models.CharField(max_length=200, default="Walk-in Customer")
    guest_count = models.PositiveIntegerField(default=1)
    cashier = models.ForeignKey(
        "users.CustomUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="settled_orders"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    is_paid = models.BooleanField(default=False)
    invoice_printed = models.BooleanField(default=False)
    posting_date = models.DateField(default=timezone.localdate)
    posting_time = models.TimeField(default=timezone.localtime)
    net_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
    rounded_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
    change_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    cancel_reason = models.TextField(blank=True)
    opening_entry = models.ForeignKey(
        "staff.POSOpeningEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    arrived_time = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-posting_date", "-posting_time"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["posting_date"]),
        ]

    def __str__(self):
        return f"{self.invoice_number or f'#{self.pk}'} — {self.customer_name}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if is_new and not self.arrived_time:
            self.arrived_time = timezone.now()
        super().save(*args, **kwargs)
        if is_new and not self.invoice_number:
            from apps.settings.models import Restaurant

            settings = Restaurant.load()
            prefix = settings.invoice_series_prefix if settings else "REST-"
            self.invoice_number = f"{prefix}{self.pk}"
            super().save(update_fields=["invoice_number"])

    def clean(self):
        super().clean()
        if self.status == CANCELLED and not self.cancel_reason:
            raise ValidationError({"cancel_reason": "A cancel reason is required."})

    def assign_order_number(self):
        """Set a sequential order number, resetting daily when settings say so."""
        from apps.settings.models import Restaurant

        if self.order_number is not None:
            return self.order_number
        settings = Restaurant.load()
        qs = Order.objects.exclude(pk=self.pk)
        if settings and settings.reset_order_number_daily:
            qs = qs.filter(posting_date=self.posting_date)
        last = qs.aggregate(max_num=models.Max("order_number"))["max_num"]
        self.order_number = (last or 0) + 1
        super().save(update_fields=["order_number"])
        return self.order_number

    def recalculate_totals(self):
        """Recalculate net_total from items and grand total (no tax)."""
        total = self.items.aggregate(t=Sum("amount"))["t"] or Decimal("0")
        self.net_total = total
        self.grand_total = self.net_total
        self.rounded_total = self.grand_total.quantize(Decimal("1"), rounding="ROUND_HALF_UP")
        self.save(
            update_fields=[
                "net_total",
                "grand_total",
                "rounded_total",
                "updated_at",
            ]
        )

    def add_item(self, item, qty=1, customer_index=1, comments="", rate=None, menu_item=None):
        """Add an item to the order, or increment qty if same item+customer+comments exists."""
        if self.status != DRAFT:
            raise ValidationError("Cannot modify a submitted or cancelled order.")
        existing = self.items.filter(item=item, customer_index=customer_index, comments=comments or "").first()
        if existing:
            existing.qty += qty
            existing.save()
            return existing
        return OrderItem.objects.create(
            order=self,
            item=item,
            qty=qty,
            customer_index=customer_index,
            comments=comments,
            rate=rate or Decimal("0"),
            menu_item=menu_item,
        )

    def remove_item(self, order_item_pk):
        """Remove an item from the order."""
        if self.status != DRAFT:
            raise ValidationError("Cannot modify a submitted or cancelled order.")
        self.items.filter(pk=order_item_pk).delete()

    @transaction.atomic
    def settle(self, payments_data, cashier=None):
        """Process payment and submit the order. Totals → tax → rounding → payments →
        change → outstanding → submit → stock."""
        if self.status != DRAFT:
            raise ValidationError("Order is already settled or cancelled.")
        if self.order_type == DINE_IN and not self.invoice_printed:
            raise ValidationError("Invoice must be printed before settling a dine-in order.")
        if cashier:
            self.cashier = cashier
        self.recalculate_totals()
        self.grand_total = self.rounded_total
        self.payments.all().delete()
        total_paid = Decimal("0")
        for entry in payments_data:
            mode_pk = entry.get("mode_of_payment") or entry.get("mode_of_payment_id")
            amount = Decimal(str(entry.get("amount", 0)))
            if amount <= 0:
                continue
            OrderPayment.objects.create(
                order=self, mode_of_payment_id=mode_pk, amount=amount, reference_no=entry.get("reference_no", "")
            )
            total_paid += amount
        if total_paid < self.grand_total:
            raise ValidationError("Payment must cover the full total.")
        self.paid_amount = total_paid
        self.change_amount = max(total_paid - self.grand_total, Decimal("0"))
        self.is_paid = True
        self.status = SUBMITTED
        self.save()
        self._deduct_stock()
        if self.order_number is None:
            self.assign_order_number()

    def _default_warehouse(self):
        """Stock deduction warehouse: settings default, falling back to the item's own."""
        from apps.settings.models import Restaurant

        settings = Restaurant.load()
        return settings.default_warehouse if settings else None

    def _deduct_stock(self):
        """Create negative stock ledger entries for all stock items in the order."""
        voucher_no = str(self.pk)
        warehouse = self._default_warehouse()
        for oi in self.items.select_related("item").only("item__is_stock_item", "item__default_warehouse", "qty"):
            if not oi.item.is_stock_item:
                continue
            wh = warehouse or oi.item.default_warehouse
            if not wh:
                continue
            StockLedgerEntry.create_entry(
                item=oi.item,
                warehouse=wh,
                actual_qty=-oi.qty,
                voucher_type="POS Order",
                voucher_no=voucher_no,
                voucher_detail_no=str(oi.pk),
            )

    def _restore_stock(self):
        """Create positive stock ledger entries reversing a submitted order's deductions."""
        voucher_no = str(self.pk)
        warehouse = self._default_warehouse()
        for oi in self.items.select_related("item").only("item__is_stock_item", "item__default_warehouse", "qty"):
            if not oi.item.is_stock_item:
                continue
            wh = warehouse or oi.item.default_warehouse
            if not wh:
                continue
            StockLedgerEntry.create_entry(
                item=oi.item,
                warehouse=wh,
                actual_qty=oi.qty,
                voucher_type="POS Order Cancellation",
                voucher_no=voucher_no,
                voucher_detail_no=str(oi.pk),
            )

    @transaction.atomic
    def cancel(self, reason):
        """Cancel the order. Reverses stock if submitted, cancels KOTs."""
        if self.status == CANCELLED:
            return
        if not reason or not reason.strip():
            raise ValidationError("A cancel reason is required.")
        self.cancel_reason = reason
        if self.status == SUBMITTED:
            self._restore_stock()
        self._cancel_kots()
        self.status = CANCELLED
        self.save(update_fields=["status", "cancel_reason", "updated_at"])

    def _cancel_kots(self):
        """Set all submitted KOTs to cancelled and create a cancellation KOT."""
        from apps.settings.models import ProductionUnit

        active_kots = self.kots.filter(status=SUBMITTED).exclude(type__in=[KOT_CANCELLED, PARTIALLY_CANCELLED])
        if not active_kots.exists():
            return
        active_kots.update(status=CANCELLED)
        items_by_dept = {}
        for oi in self.items.select_related("item").only("item__department", "item_name", "qty", "comments"):
            items_by_dept.setdefault(oi.item.department, []).append(oi)
        production_units = {pu.department: pu for pu in ProductionUnit.objects.all()}
        for dept, order_items in items_by_dept.items():
            pu = production_units.get(dept)
            if not pu:
                continue
            original_names = active_kots.filter(production_unit=pu).values_list("kot_number", flat=True)
            kot = KOT.objects.create(
                order=self,
                production_unit=pu,
                type=KOT_CANCELLED,
                order_number=self.order_number,
                original_kots=",".join(original_names),
            )
            kot.kot_number = f"CNCL-KOT-{kot.pk:04d}"
            kot.save(update_fields=["kot_number"])
            kot_items = [
                KOTItem(
                    kot=kot,
                    item=oi.item,
                    item_name=oi.item_name,
                    qty=Decimal("0"),
                    cancelled_qty=oi.qty,
                    comments=oi.comments,
                    customer_index=oi.customer_index,
                )
                for oi in order_items
            ]
            KOTItem.objects.bulk_create(kot_items)

    def generate_kots(self, previous_items):
        """Diff current items vs previous and generate KOTs per production unit.

        Args:
            previous_items: list of dicts with keys item_id, qty, customer_index, comments.
        """
        current_map = {}
        for oi in self.items.select_related("item").only(
            "item_id", "item__department", "item__item_name", "qty", "customer_index", "comments"
        ):
            key = (oi.item_id, oi.customer_index, oi.comments or "")
            current_map[key] = current_map.get(key, Decimal("0")) + oi.qty

        previous_map = {}
        for pi in previous_items:
            key = (pi["item_id"], pi.get("customer_index", 1), pi.get("comments", ""))
            previous_map[key] = previous_map.get(key, Decimal("0")) + Decimal(str(pi["qty"]))

        new_or_increased = {}
        removed_or_decreased = {}
        for key, new_qty in current_map.items():
            old_qty = previous_map.get(key, Decimal("0"))
            if new_qty > old_qty:
                new_or_increased[key] = new_qty - old_qty
            elif new_qty < old_qty:
                removed_or_decreased[key] = old_qty - new_qty
        for key, old_qty in previous_map.items():
            if key not in current_map:
                removed_or_decreased[key] = old_qty

        if not new_or_increased and not removed_or_decreased:
            return []

        from apps.settings.models import ProductionUnit

        item_ids = {k[0] for k in list(new_or_increased) + list(removed_or_decreased)}
        items_cache = {i.pk: i for i in Item.objects.filter(pk__in=item_ids).only("department", "item_name")}
        production_units = {pu.department: pu for pu in ProductionUnit.objects.all()}

        created_kots = []
        if new_or_increased:
            created_kots += self._generate_kot_type(
                new_or_increased, items_cache, production_units, NEW_ORDER, PARTIALLY_CANCELLED, is_cancel=False
            )
        if removed_or_decreased:
            created_kots += self._generate_kot_type(
                removed_or_decreased, items_cache, production_units, PARTIALLY_CANCELLED, KOT_CANCELLED, is_cancel=True
            )
        return created_kots

    def _generate_kot_type(self, diffs, items_cache, production_units, default_type, cancel_type, is_cancel):
        """Generate KOTs for a set of item diffs, grouped by production unit department."""
        by_dept = {}
        for (item_id, customer_index, comments), qty in diffs.items():
            item = items_cache.get(item_id)
            if not item:
                continue
            by_dept.setdefault(item.department, []).append((item, customer_index, comments, qty))

        created = []
        for dept, entries in by_dept.items():
            pu = production_units.get(dept)
            if not pu:
                continue
            if is_cancel:
                kot_type = PARTIALLY_CANCELLED
                existing = self.kots.filter(production_unit=pu, status=SUBMITTED).exclude(
                    type__in=[KOT_CANCELLED, PARTIALLY_CANCELLED]
                )
                original_names = list(existing.values_list("kot_number", flat=True))
            else:
                existing_kot = (
                    self.kots.filter(production_unit=pu, status=SUBMITTED)
                    .exclude(type__in=[KOT_CANCELLED, PARTIALLY_CANCELLED])
                    .first()
                )
                kot_type = ORDER_MODIFIED if existing_kot else NEW_ORDER
                original_names = []

            kot = KOT.objects.create(
                order=self,
                production_unit=pu,
                type=kot_type,
                order_number=self.order_number,
                original_kots=",".join(original_names),
            )
            prefix = "CNCL-KOT-" if is_cancel else "KOT-"
            kot.kot_number = f"{prefix}{kot.pk:04d}"
            kot.save(update_fields=["kot_number"])

            kot_items = []
            for item, customer_index, comments, qty in entries:
                kot_items.append(
                    KOTItem(
                        kot=kot,
                        item=item,
                        item_name=item.item_name,
                        qty=Decimal("0") if is_cancel else qty,
                        cancelled_qty=qty if is_cancel else Decimal("0"),
                        comments=comments,
                        customer_index=customer_index,
                    )
                )
            KOTItem.objects.bulk_create(kot_items)
            created.append(kot)
        return created


class OrderItem(BaseModel):
    """A single line item in an order."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="order_items")
    item_name = models.CharField(max_length=200)
    qty = models.DecimalField(max_digits=10, decimal_places=2)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    customer_index = models.PositiveIntegerField(default=1)
    comments = models.CharField(max_length=200, blank=True)
    menu_item = models.ForeignKey("menu.MenuItem", on_delete=models.SET_NULL, null=True, blank=True)
    synced = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.item_name} x{self.qty}"

    def save(self, *args, **kwargs):
        if not self.item_name and self.item_id:
            self.item_name = self.item.item_name
        if self.rate is None:
            self.rate = Decimal("0")
        self.amount = (self.qty * self.rate).quantize(TWO_PLACES)
        super().save(*args, **kwargs)


class OrderPayment(BaseModel):
    """A payment line within an order."""

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    mode_of_payment = models.ForeignKey(ModeOfPayment, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference_no = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.mode_of_payment.name}: {self.amount}"


class KOT(BaseModel):
    """Kitchen Order Ticket — immutable once generated."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="kots")
    production_unit = models.ForeignKey("settings.ProductionUnit", on_delete=models.PROTECT, related_name="kots")
    type = models.CharField(max_length=25, choices=KOT_TYPE_CHOICES)
    kot_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(
        max_length=15, choices=[(SUBMITTED, "Submitted"), (CANCELLED, "Cancelled")], default=SUBMITTED
    )
    posting_datetime = models.DateTimeField(auto_now_add=True)
    order_number = models.PositiveIntegerField(null=True, blank=True)
    original_kots = models.TextField(blank=True)

    class Meta:
        ordering = ["-posting_datetime"]

    def __str__(self):
        return f"{self.kot_number} — {self.type}"


class KOTItem(BaseModel):
    """An item line on a KOT."""

    kot = models.ForeignKey(KOT, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    item_name = models.CharField(max_length=200)
    qty = models.DecimalField(max_digits=10, decimal_places=2)
    cancelled_qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    comments = models.CharField(max_length=200, blank=True)
    customer_index = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.item_name} x{self.qty}"

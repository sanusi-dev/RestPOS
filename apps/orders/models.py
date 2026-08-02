from decimal import Decimal
from uuid import uuid4

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

TICKET_KITCHEN = "kitchen"
TICKET_BAR = "bar"
TICKET_TYPE_CHOICES = [
    (TICKET_KITCHEN, "Kitchen"),
    (TICKET_BAR, "Bar"),
]
KOT_PRINT_PENDING = "PENDING"
KOT_PRINTED = "PRINTED"
KOT_PRINT_CANCELLED = "CANCELLED"
KOT_PRINT_STATUS_CHOICES = [
    (KOT_PRINT_PENDING, "Pending"),
    (KOT_PRINTED, "Printed"),
    (KOT_PRINT_CANCELLED, "Cancelled"),
]

CANCEL_REASON_WRONG_ORDER = "wrong_order"
CANCEL_REASON_CUSTOMER_CHANGED_MIND = "customer_changed_mind"
CANCEL_REASON_CASHIER_ERROR = "cashier_error"
CANCEL_REASON_OTHER = "other"
CANCEL_REASON_CHOICES = [
    (CANCEL_REASON_WRONG_ORDER, "Wrong order"),
    (CANCEL_REASON_CUSTOMER_CHANGED_MIND, "Customer changed mind"),
    (CANCEL_REASON_CASHIER_ERROR, "Cashier error"),
    (CANCEL_REASON_OTHER, "Other"),
]


def _ticket_type_for_department(department):
    return TICKET_KITCHEN if department == "FOOD" else TICKET_BAR


def _ticket_prefix_for_type(ticket_type):
    return "KOT" if ticket_type == TICKET_KITCHEN else "BOT"


TWO_PLACES = Decimal("0.01")


class OrderSequence(BaseModel):
    """Persistent counter for sequential order numbers, one row per series."""

    name = models.CharField(max_length=50, unique=True)
    current_value = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.name} → {self.current_value}"


class Order(BaseModel):
    """A POS order — the single source of truth for items, payments, and status."""

    invoice_number = models.CharField(max_length=50, unique=True, null=True, blank=True, editable=False)
    order_number = models.PositiveIntegerField(db_index=True, null=True, blank=True, editable=False)
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
    cancel_reason = models.CharField(max_length=50, choices=CANCEL_REASON_CHOICES, blank=True)
    cancel_reason_note = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_orders",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    opening_entry = models.ForeignKey(
        "staff.POSOpeningEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    arrived_time = models.DateTimeField(null=True, blank=True, editable=False)
    is_return = models.BooleanField(default=False, editable=False)
    return_against = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="return_orders"
    )

    class Meta:
        ordering = ["-posting_date", "-posting_time"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["posting_date"]),
        ]

    def __str__(self):
        return f"{self.invoice_number or f'#{self.pk}'} — {self.customer_name}"

    def save(self, *args, **kwargs):
        if self.pk and self.kots.exists() and self.status == DRAFT:
            previous = type(self).objects.only("order_type", "guest_count").get(pk=self.pk)
            if (self.order_type, self.guest_count, self.customer_name) != (
                previous.order_type,
                previous.guest_count,
                previous.customer_name,
            ):
                raise ValidationError("This order was sent to the kitchen or bar. Cancel it before making changes.")
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
        if self.is_return:
            if not self.return_against_id:
                raise ValidationError({"return_against": "A return order must reference the original order."})
            if self.return_against.is_return:
                raise ValidationError({"return_against": "Cannot return against another return order."})

    def delete(self, *args, **kwargs):
        if self.kots.exists():
            raise ValidationError("Sent orders cannot be deleted; cancel the order instead.")
        return super().delete(*args, **kwargs)

    def assign_order_number(self):
        """Assign the next sequential order number atomically."""
        if self.order_number is not None:
            return self.order_number
        with transaction.atomic():
            seq = OrderSequence.objects.select_for_update().get(name="order")
            seq.current_value += 1
            seq.save(update_fields=["current_value"])
            self.order_number = seq.current_value
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

    def _ensure_editable(self):
        """Reject edits after a kitchen or bar ticket has been created."""
        if self.status != DRAFT:
            raise ValidationError("Cannot modify a submitted or cancelled order.")
        if self.kots.exists():
            raise ValidationError("This order was sent to the kitchen or bar. Cancel it before making changes.")

    def add_item(self, item, qty=1, customer_index=1, comments="", rate=None, menu_item=None):
        """Add an item to the order, or increment qty if same item+customer+comments exists."""
        self._ensure_editable()
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
        self._ensure_editable()
        self.items.filter(pk=order_item_pk).delete()

    def change_guest_count(self, new_count):
        """Set the guest count. Cannot drop below a guest who still has items — that
        would leave orphaned rows tagged to a hidden customer slot and skew per-customer
        analytics. Submits/cancellations stay untouched."""
        self._ensure_editable()
        max_index = self.items.aggregate(m=models.Max("customer_index"))["m"] or 1
        if new_count < max_index:
            raise ValidationError(f"Remove Customer {max_index}'s items before lowering the guest count.")
        self.guest_count = new_count
        self.save(update_fields=["guest_count", "updated_at"])

    @transaction.atomic
    def settle(self, payments_data, cashier=None):
        """Process payment and submit the order. Totals → tax → rounding → payments →
        change → outstanding → submit → stock."""
        if self.status != DRAFT:
            raise ValidationError("Order is already settled or cancelled.")
        if not self.items.exists():
            raise ValidationError("Cannot settle an order with no items.")
        if cashier:
            self.cashier = cashier
        self.recalculate_totals()
        self.grand_total = self.rounded_total
        if self.is_return and self.grand_total >= 0:
            raise ValidationError("Return order total must be negative.")
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
        if not self.is_return and total_paid < self.grand_total:
            raise ValidationError("Payment must cover the full total.")
        if self.is_return and total_paid < abs(self.grand_total):
            raise ValidationError("Refund amounts must cover the full return total.")
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
        """Create negative stock ledger entries for all stock items in the order.

        For return orders, negative qty creates positive stock entries (restoration).
        """
        voucher_no = str(self.pk)
        warehouse = self._default_warehouse()
        # TODO(Phase 10): return orders should use voucher_type="Sales Return"
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
    def cancel(self, reason, cancelled_by=None, reason_note=""):
        """Cancel the order. Reverses stock if submitted, cancels KOTs.

        Payment rows are preserved for audit — the cancelled order retains its
        original items, payments, and totals. Shift close (Phase 7) excludes
        cancelled orders by filtering on status != CANCELLED.
        """
        if self.status == CANCELLED:
            return
        if not reason or not reason.strip():
            raise ValidationError("A cancel reason is required.")
        reason = reason.strip()
        reason_note = reason_note.strip()
        if reason not in dict(CANCEL_REASON_CHOICES):
            reason_note = reason_note or reason
            reason = CANCEL_REASON_OTHER
        self.cancel_reason = reason
        self.cancel_reason_note = reason_note
        self.cancelled_by = cancelled_by
        self.cancelled_at = timezone.now()
        if self.status == SUBMITTED:
            self._restore_stock()
        self._cancel_kots()
        self.status = CANCELLED
        self.save(
            update_fields=[
                "status",
                "cancel_reason",
                "cancel_reason_note",
                "cancelled_by",
                "cancelled_at",
                "updated_at",
            ]
        )

    @transaction.atomic
    def cancel_sent_order(self, reason, reason_note="", cancelled_by=None):
        """Cancel an unpaid order after its kitchen or bar tickets were sent."""
        if self.status != DRAFT:
            raise ValidationError("Only draft orders can be cancelled from the POS.")
        if not self.kots.exists():
            raise ValidationError("Only an order already sent to the kitchen or bar can be cancelled here.")
        if reason not in dict(CANCEL_REASON_CHOICES):
            raise ValidationError("Choose a valid cancellation reason.")

        self.kots.update(status=CANCELLED, print_status=KOT_PRINT_CANCELLED)
        self.status = CANCELLED
        self.cancel_reason = reason
        self.cancel_reason_note = reason_note.strip()
        self.cancelled_by = cancelled_by
        self.cancelled_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "cancel_reason",
                "cancel_reason_note",
                "cancelled_by",
                "cancelled_at",
                "updated_at",
            ]
        )

    def _cancel_kots(self):
        """Set all submitted KOTs to cancelled and create a cancellation KOT."""
        from apps.settings.models import ProductionUnit

        active_kots = list(self.kots.filter(status=SUBMITTED).exclude(type__in=[KOT_CANCELLED, PARTIALLY_CANCELLED]))
        if not active_kots:
            return
        active_kot_ids = [kot.pk for kot in active_kots]
        self.kots.filter(pk__in=active_kot_ids).update(status=CANCELLED, print_status=KOT_PRINT_CANCELLED)
        items_by_dept = {}
        for oi in self.items.select_related("item").only("item__department", "item_name", "qty", "comments"):
            items_by_dept.setdefault(oi.item.department, []).append(oi)
        production_units = {pu.department: pu for pu in ProductionUnit.objects.all()}
        for dept, order_items in items_by_dept.items():
            pu = production_units.get(dept)
            if not pu:
                continue
            if self.order_type == TAKE_AWAY and pu.block_takeaway_kot:
                continue
            original_names = [kot.kot_number for kot in active_kots if kot.production_unit_id == pu.pk]
            kot = KOT.objects.create(
                order=self,
                production_unit=pu,
                type=KOT_CANCELLED,
                ticket_type=_ticket_type_for_department(dept),
                print_status=KOT_PRINT_PENDING,
                created_by=self.cancelled_by,
                kot_number=f"TMP-{uuid4().hex}",
                order_number=self.order_number,
                original_kots=",".join(original_names),
            )
            kot.kot_number = f"CNCL-{_ticket_prefix_for_type(kot.ticket_type)}-{kot.pk:04d}"
            KOT.objects.filter(pk=kot.pk).update(kot_number=kot.kot_number)
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

    @transaction.atomic
    def make_return(self):
        """Create a draft return order with negative items and payments.

        Mirrors ERPNext's make_sales_return: creates a new Order with is_return=True,
        return_against=self, and all items/payments negated. The return is a draft
        that must be reviewed and submitted from the backoffice.
        """
        if self.status != SUBMITTED:
            raise ValidationError("Can only return submitted orders.")
        if self.is_return:
            raise ValidationError("Cannot return a return order.")

        return_order = Order.objects.create(
            order_type=self.order_type,
            guest_count=self.guest_count,
            is_return=True,
            return_against=self,
        )
        for oi in self.items.all():
            OrderItem.objects.create(
                order=return_order,
                item=oi.item,
                item_name=oi.item_name,
                qty=-oi.qty,
                rate=oi.rate,
                customer_index=oi.customer_index,
                comments=oi.comments,
                menu_item=oi.menu_item,
            )
        for payment in self.payments.all():
            OrderPayment.objects.create(
                order=return_order,
                mode_of_payment=payment.mode_of_payment,
                amount=-payment.amount,
                reference_no=payment.reference_no,
            )
        return_order.recalculate_totals()
        return return_order

    @transaction.atomic
    def create_tickets(self, created_by=None):
        """Create one immutable kitchen ticket and one bar ticket from the order snapshot."""
        if self.status != DRAFT:
            raise ValidationError("Only draft orders can be sent to the kitchen or bar.")
        if self.kots.exists():
            raise ValidationError("This order has already been sent to the kitchen or bar.")
        if not self.items.exists():
            raise ValidationError("Add at least one item before sending the order.")

        from apps.settings.models import ProductionUnit

        items_by_department = {}
        for order_item in self.items.select_related("item"):
            items_by_department.setdefault(order_item.item.department, []).append(order_item)
        production_units = {pu.department: pu for pu in ProductionUnit.objects.all()}
        planned_tickets = []
        missing_departments = []
        for department, order_items in items_by_department.items():
            production_unit = production_units.get(department)
            if self.order_type == TAKE_AWAY and production_unit and production_unit.block_takeaway_kot:
                continue
            if not production_unit:
                missing_departments.append(department)
                continue
            planned_tickets.append((department, order_items, production_unit))

        if missing_departments:
            labels = ", ".join("Food" if department == "FOOD" else "Drinks" for department in missing_departments)
            raise ValidationError(f"Configure a production unit before sending: {labels}.")
        if not planned_tickets:
            raise ValidationError("No kitchen or bar ticket is required for this order.")
        created = []

        for department, order_items, production_unit in planned_tickets:
            ticket_type = _ticket_type_for_department(department)
            kot = KOT.objects.create(
                order=self,
                production_unit=production_unit,
                type=NEW_ORDER,
                ticket_type=ticket_type,
                print_status=KOT_PRINT_PENDING,
                created_by=created_by,
                kot_number=f"TMP-{uuid4().hex}",
                order_number=self.order_number,
            )
            kot.kot_number = f"{_ticket_prefix_for_type(ticket_type)}-{kot.pk:04d}"
            KOT.objects.filter(pk=kot.pk).update(kot_number=kot.kot_number)
            KOTItem.objects.bulk_create(
                [
                    KOTItem(
                        kot=kot,
                        item=order_item.item,
                        item_name=order_item.item_name,
                        qty=order_item.qty,
                        comments=order_item.comments,
                        customer_index=order_item.customer_index,
                    )
                    for order_item in order_items
                ]
            )
            created.append(kot)

        self.items.update(synced=True)
        return created

    def generate_kots(self, previous_items=None, created_by=None):
        """Create the initial departmental tickets without in-place order diffing."""
        if previous_items:
            raise ValidationError("Sent orders cannot be modified; cancel the order and create a new one.")
        return self.create_tickets(created_by=created_by)


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
        return f"{self.item_name}"

    def save(self, *args, **kwargs):
        if self.order_id and self.order.kots.exists():
            raise ValidationError("This order was sent to the kitchen or bar. Cancel it before making changes.")
        if not self.item_name and self.item_id:
            self.item_name = self.item.item_name
        if self.rate is None:
            self.rate = Decimal("0")
        self.amount = (self.qty * self.rate).quantize(TWO_PLACES)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.order_id and self.order.kots.exists():
            raise ValidationError("This order was sent to the kitchen or bar. Cancel it before making changes.")
        return super().delete(*args, **kwargs)


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
    ticket_type = models.CharField(max_length=10, choices=TICKET_TYPE_CHOICES, default=TICKET_KITCHEN)
    status = models.CharField(
        max_length=15, choices=[(SUBMITTED, "Submitted"), (CANCELLED, "Cancelled")], default=SUBMITTED
    )
    print_status = models.CharField(max_length=15, choices=KOT_PRINT_STATUS_CHOICES, default=KOT_PRINT_PENDING)
    created_by = models.ForeignKey(
        "users.CustomUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_kots"
    )
    posting_datetime = models.DateTimeField(auto_now_add=True)
    order_number = models.PositiveIntegerField(null=True, blank=True)
    original_kots = models.TextField(blank=True)

    class Meta:
        ordering = ["-posting_datetime"]

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            immutable_fields = (
                "order_id",
                "production_unit_id",
                "type",
                "kot_number",
                "ticket_type",
                "created_by_id",
                "order_number",
                "original_kots",
            )
            if any(getattr(self, field) != getattr(previous, field) for field in immutable_fields):
                raise ValidationError("KOT snapshots cannot be edited after creation.")
        super().save(*args, **kwargs)

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

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            immutable_fields = (
                "kot_id",
                "item_id",
                "item_name",
                "qty",
                "cancelled_qty",
                "comments",
                "customer_index",
            )
            if any(getattr(self, field) != getattr(previous, field) for field in immutable_fields):
                raise ValidationError("KOT item snapshots cannot be edited after creation.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("KOT item snapshots cannot be deleted after creation.")

    def __str__(self):
        return f"{self.item_name} x{self.qty}"

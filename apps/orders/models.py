from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.inventory.models import Bin, Item, StockLedgerEntry
from apps.payments.models import ModeOfPayment, PaymentGLMapping
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
KOT_CANCELLED = "Cancelled"
KOT_TYPE_CHOICES = [
    (NEW_ORDER, "New Order"),
    (KOT_CANCELLED, "Cancelled"),
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
    rounding_adjustment = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
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
    stock_warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="order_stock_snapshots",
    )
    arrived_time = models.DateTimeField(null=True, blank=True, editable=False)
    submitted_at = models.DateTimeField(null=True, blank=True, editable=False)
    invoice_printed_at = models.DateTimeField(null=True, blank=True, editable=False)
    invoice_printed_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="printed_orders",
    )
    is_return = models.BooleanField(default=False, editable=False)
    return_against = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="return_orders"
    )

    class Meta:
        ordering = ["-posting_date", "-posting_time"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["posting_date"]),
            models.Index(fields=["status", "updated_at"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(guest_count__gte=1), name="orders_guest_count_gte_one"),
            models.CheckConstraint(
                condition=~Q(status=CANCELLED) | ~Q(cancel_reason=""),
                name="orders_cancelled_has_reason",
            ),
            models.UniqueConstraint(
                fields=["order_number"],
                condition=Q(order_number__isnull=False),
                name="orders_order_number_unique",
            ),
        ]

    def __str__(self):
        return f"{self.invoice_number or f'#{self.pk}'} — {self.customer_name}"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            allow_cancellation = getattr(self, "_allow_cancellation", False)
            allow_submit = getattr(self, "_allow_submit", False)

            if previous.status in {SUBMITTED, CANCELLED} and not allow_cancellation:
                raise ValidationError("Submitted or cancelled orders cannot be modified.")
            if previous.status == DRAFT and self.status == SUBMITTED and not allow_submit:
                raise ValidationError("Only settlement can submit an order.")
            if previous.status == DRAFT and self.status == CANCELLED and not allow_cancellation:
                raise ValidationError("Use the order cancellation flow to cancel an order.")
            if (self.is_return, self.return_against_id) != (previous.is_return, previous.return_against_id):
                raise ValidationError("An order's return status and source cannot be changed.")
            if previous.stock_warehouse_id and self.stock_warehouse_id != previous.stock_warehouse_id:
                raise ValidationError("The stock warehouse snapshot cannot be changed.")
            if previous.invoice_printed and not self.invoice_printed:
                raise ValidationError("A printed receipt cannot be marked as unprinted.")
            if (
                previous.status == DRAFT
                and not allow_cancellation
                and (previous.invoice_printed or previous.kots.exists())
            ):
                draft_fields = ("order_type", "customer_name", "guest_count")
                if any(getattr(self, field) != getattr(previous, field) for field in draft_fields):
                    message = (
                        "This receipt has been printed. Draft edits are no longer allowed."
                        if previous.invoice_printed
                        else "This order was sent to the kitchen or bar. Cancel it before making changes."
                    )
                    raise ValidationError(message)
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
            if self.return_against.status != SUBMITTED:
                raise ValidationError({"return_against": "A return must reference a submitted order."})

    @transaction.atomic
    def delete(self, *args, **kwargs):
        if self.pk:
            persisted = type(self).objects.select_for_update().get(pk=self.pk)
            if persisted.status != DRAFT:
                raise ValidationError("Submitted or cancelled orders cannot be deleted.")
            if persisted.invoice_printed:
                raise ValidationError("Printed orders cannot be deleted; cancel the order instead.")
        else:
            persisted = self
        if persisted.kots.exists():
            raise ValidationError("Sent orders cannot be deleted; cancel the order instead.")
        persisted._release_drink_reservations()
        persisted.items.all().delete()
        return models.Model.delete(persisted, *args, **kwargs)

    def assign_order_number(self):
        """Assign the next sequential order number atomically."""
        if self.order_number is not None:
            return self.order_number
        if self.status != DRAFT:
            raise ValidationError("Only draft orders can receive an order number.")
        with transaction.atomic():
            sequence, _created = OrderSequence.objects.get_or_create(
                name="order",
                defaults={"current_value": 0},
            )
            seq = OrderSequence.objects.select_for_update().get(pk=sequence.pk)
            if _created:
                seq.current_value = (
                    type(self).objects.aggregate(max_number=models.Max("order_number"))["max_number"] or 0
                )
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
        self.rounding_adjustment = self.rounded_total - self.grand_total
        self.save(
            update_fields=[
                "net_total",
                "grand_total",
                "rounded_total",
                "rounding_adjustment",
                "updated_at",
            ]
        )

    def _ensure_editable(self):
        """Reject edits after a kitchen or bar ticket has been created."""
        persisted = type(self).objects.only("status", "invoice_printed").get(pk=self.pk) if self.pk else self
        if persisted.status != DRAFT:
            raise ValidationError("Cannot modify a submitted or cancelled order.")
        if persisted.invoice_printed:
            raise ValidationError("This receipt has been printed. Draft edits are no longer allowed.")
        if self.kots.exists():
            raise ValidationError("This order was sent to the kitchen or bar. Cancel it before making changes.")

    @transaction.atomic
    def add_item(self, item, qty=1, customer_index=1, comments="", rate=None, menu_item=None, item_name=None):
        """Add an item to the order, or increment qty if same item+customer+comments exists."""
        order = type(self).objects.select_for_update().get(pk=self.pk)
        order._ensure_editable()
        try:
            qty = Decimal(str(qty))
            rate = Decimal(str(rate)) if rate is not None else None
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise ValidationError("Quantity and rate must be valid decimals.") from exc
        if not qty.is_finite() or qty <= 0:
            raise ValidationError("Quantity must be greater than zero.")
        if rate is None or not rate.is_finite() or rate < 0:
            raise ValidationError("A valid non-negative selling rate is required.")
        if customer_index < 1 or customer_index > order.guest_count:
            raise ValidationError("The customer card is outside this order's guest count.")
        order._validate_pos_item(item)
        drink_quantities = order._drink_quantities()
        if item.department == "DRINKS":
            drink_quantities[item.pk] = drink_quantities.get(item.pk, Decimal("0")) + qty
        order._set_drink_reservations(drink_quantities)
        existing = order.items.filter(item=item, customer_index=customer_index, comments=comments or "").first()
        if existing:
            existing.qty += qty
            existing.save()
            self.refresh_from_db()
            return existing
        created = OrderItem.objects.create(
            order=order,
            item=item,
            qty=qty,
            customer_index=customer_index,
            comments=comments,
            rate=rate,
            item_name=item_name or item.item_name,
            menu_item=menu_item,
        )
        self.refresh_from_db()
        return created

    @transaction.atomic
    def update_item_quantity(self, order_item_pk, qty):
        """Set a draft line quantity, reserving or releasing drink stock atomically."""
        order = type(self).objects.select_for_update().get(pk=self.pk)
        order._ensure_editable()
        try:
            qty = Decimal(str(qty))
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise ValidationError("Quantity must be a valid decimal.") from exc
        if not qty.is_finite():
            raise ValidationError("Quantity must be a valid decimal.")
        line = order.items.select_related("item").filter(pk=order_item_pk).first()
        if line is None:
            raise ValidationError("That order line no longer exists.")
        drink_quantities = order._drink_quantities()
        if line.department == "DRINKS":
            drink_quantities[line.item_id] -= line.qty
            if qty > 0:
                drink_quantities[line.item_id] += qty
            if drink_quantities[line.item_id] == 0:
                del drink_quantities[line.item_id]
        order._set_drink_reservations(drink_quantities)
        if qty <= 0:
            line.delete()
            self.refresh_from_db()
            return None
        line.qty = qty
        line.save()
        self.refresh_from_db()
        return line

    @transaction.atomic
    def remove_item(self, order_item_pk):
        """Remove an item from the order."""
        return self.update_item_quantity(order_item_pk, Decimal("0"))

    @transaction.atomic
    def clear_items(self):
        """Remove every editable draft line and release its drink reservations."""
        order = type(self).objects.select_for_update().get(pk=self.pk)
        order._ensure_editable()
        order._set_drink_reservations({})
        order.items.all().delete()
        order.recalculate_totals()
        self.refresh_from_db()

    def _validate_pos_item(self, item):
        if item.disabled or not item.is_sales_item:
            raise ValidationError("That menu item is no longer available.")
        if item.department == "DRINKS" and not item.is_stock_item:
            raise ValidationError(f"{item.item_name} is a drink but is not configured as a stock item.")

    def _drink_quantities(self):
        if self.is_return:
            return {}
        rows = (
            self.items.filter(Q(department="DRINKS") | Q(department__isnull=True, item__department="DRINKS"))
            .values("item_id")
            .annotate(qty=Sum("qty"))
            .order_by("item_id")
        )
        return {row["item_id"]: row["qty"] for row in rows if row["qty"] > 0}

    def _reservations_initialized(self):
        return bool(self.stock_warehouse_id) and not self.is_return

    def _reservation_warehouse(self, *, required):
        from apps.settings.models import Restaurant

        restaurant = Restaurant.objects.select_for_update().first()
        warehouse = (
            type(restaurant).objects.select_related("default_warehouse").get(pk=restaurant.pk).default_warehouse
            if restaurant
            else None
        )
        if required and warehouse is None:
            raise ValidationError("Configure the Bar/POS warehouse before selling drinks.")
        if warehouse is not None and warehouse.disabled:
            raise ValidationError("The configured Bar/POS warehouse is disabled.")
        if self.stock_warehouse_id and warehouse and self.stock_warehouse_id != warehouse.pk:
            raise ValidationError("The Bar/POS warehouse changed while this order was open. Clear or cancel the order.")
        return self.stock_warehouse or warehouse

    def _locked_drink_bins(self, item_ids, warehouse):
        item_ids = sorted(set(item_ids))
        existing_ids = set(
            Bin.objects.filter(item_id__in=item_ids, warehouse=warehouse).values_list("item_id", flat=True)
        )
        for item_id in item_ids:
            if item_id not in existing_ids:
                Bin.objects.get_or_create(item_id=item_id, warehouse=warehouse)
        return {
            bin_obj.item_id: bin_obj
            for bin_obj in Bin.objects.select_for_update()
            .filter(item_id__in=item_ids, warehouse=warehouse)
            .order_by("item_id")
        }

    def _set_drink_reservations(self, target_quantities):
        """Synchronize this draft's aggregate drink reservation to target quantities."""
        if self.is_return:
            return
        initialized = self._reservations_initialized()
        current_quantities = self._drink_quantities() if initialized else {}
        item_ids = set(current_quantities) | set(target_quantities)
        if not item_ids:
            return
        if initialized and self.stock_warehouse_id:
            warehouse = self.stock_warehouse
            increasing = any(
                target_quantities.get(item_id, Decimal("0")) > current_quantities.get(item_id, Decimal("0"))
                for item_id in item_ids
            )
            if warehouse.disabled and increasing:
                raise ValidationError("The order's Bar/POS warehouse snapshot is disabled.")
        else:
            warehouse = self._reservation_warehouse(required=bool(target_quantities))
        items = {item.pk: item for item in Item.objects.filter(pk__in=item_ids).order_by("pk")}
        for item_id in target_quantities:
            item = items.get(item_id)
            if item is None or item.department != "DRINKS" or not item.is_stock_item:
                name = item.item_name if item else "This drink"
                raise ValidationError(f"{name} is not configured as a stock-tracked drink.")
        if warehouse is None:
            return
        bins = self._locked_drink_bins(item_ids, warehouse)
        for item_id in sorted(item_ids):
            bin_obj = bins[item_id]
            owned = current_quantities.get(item_id, Decimal("0"))
            target = target_quantities.get(item_id, Decimal("0"))
            increase = target - owned
            available_for_order = bin_obj.actual_qty - bin_obj.reserved_qty + owned
            if increase > 0 and target > available_for_order:
                raise ValidationError(f"Insufficient stock for {items[item_id].item_name} in {warehouse.name}.")
            new_reserved = bin_obj.reserved_qty + increase
            if new_reserved < 0:
                raise ValidationError("Stock reservation data is inconsistent; manager review is required.")
            bin_obj.reserved_qty = new_reserved
            bin_obj.save(update_fields=["reserved_qty", "updated_at"])
        snapshot_id = warehouse.pk if target_quantities else None
        if self.stock_warehouse_id != snapshot_id:
            type(self).objects.filter(pk=self.pk).update(stock_warehouse_id=snapshot_id, updated_at=timezone.now())
            self.stock_warehouse_id = snapshot_id

    def _release_drink_reservations(self):
        if not self._reservations_initialized():
            return
        self._set_drink_reservations({})

    def change_guest_count(self, new_count):
        """Set the guest count. Cannot drop below a guest who still has items — that
        would leave orphaned rows tagged to a hidden customer slot and skew per-customer
        analytics. Submits/cancellations stay untouched."""
        self._ensure_editable()
        if new_count < 1 or new_count > 50:
            raise ValidationError("Guest count must be between 1 and 50.")
        max_index = self.items.aggregate(m=models.Max("customer_index"))["m"] or 1
        if new_count < max_index:
            raise ValidationError(f"Remove Customer {max_index}'s items before lowering the guest count.")
        self.guest_count = new_count
        self.save(update_fields=["guest_count", "updated_at"])

    def _validate_payment_data(self, payments_data, opening_entry):
        """Resolve and validate payment rows before changing the order."""
        if not isinstance(payments_data, (list, tuple)) or not payments_data:
            raise ValidationError("At least one payment is required.")

        opening_mode_ids = set(opening_entry.opening_payments.values_list("mode_of_payment_id", flat=True))
        payment_rows = []
        for row_number, entry in enumerate(payments_data, start=1):
            if not isinstance(entry, dict):
                raise ValidationError(f"Payment row {row_number} is malformed.")

            try:
                amount = Decimal(str(entry.get("amount")))
                if not amount.is_finite() or amount != amount.quantize(TWO_PLACES):
                    raise InvalidOperation
            except InvalidOperation, TypeError, ValueError:
                raise ValidationError(f"Payment row {row_number} has a malformed amount.") from None
            if amount < 0:
                raise ValidationError(f"Payment row {row_number} amount must not be negative.")
            if amount == 0:
                continue

            mode_reference = entry.get("mode_of_payment")
            if mode_reference is None:
                mode_reference = entry.get("mode_of_payment_id")
            if isinstance(mode_reference, ModeOfPayment):
                mode_pk = mode_reference.pk
            else:
                try:
                    if isinstance(mode_reference, bool):
                        raise ValueError
                    mode_pk = int(mode_reference)
                except TypeError, ValueError:
                    raise ValidationError(f"Payment row {row_number} has an invalid payment mode.") from None

            mode = ModeOfPayment.objects.select_related("gl_mapping").filter(pk=mode_pk).first()
            if mode is None:
                raise ValidationError(f"Payment row {row_number} has an invalid payment mode.")
            if not mode.enabled:
                raise ValidationError(f"Payment mode {mode.name} is disabled.")
            if mode.pk not in opening_mode_ids:
                raise ValidationError(f"Payment mode {mode.name} was not declared when the shift opened.")
            try:
                mapping = mode.gl_mapping
            except PaymentGLMapping.DoesNotExist:
                raise ValidationError(f"Payment mode {mode.name} has no GL mapping.") from None
            if not mapping.default_account.strip():
                raise ValidationError(f"Payment mode {mode.name} has no GL mapping.")

            reference_no = str(entry.get("reference_no", "") or "").strip()
            if len(reference_no) > 100:
                raise ValidationError(f"Payment row {row_number} has a reference that is too long.")

            payment_rows.append(
                {
                    "mode": mode,
                    "amount": amount,
                    "reference_no": reference_no,
                }
            )
        if not payment_rows:
            raise ValidationError("At least one payment is required.")
        return payment_rows

    def _snapshot_stock_warehouse(self):
        """Validate or capture the configured warehouse for this transaction."""
        from apps.settings.models import Restaurant

        settings = Restaurant.objects.select_for_update().first()
        warehouse = settings.default_warehouse if settings else None
        if warehouse is not None and warehouse.disabled:
            raise ValidationError("Restaurant.default_warehouse is disabled.")
        has_drinks = self.items.filter(
            Q(department="DRINKS") | Q(department__isnull=True, item__department="DRINKS")
        ).exists()
        if has_drinks and warehouse is None:
            raise ValidationError("Configure the Bar/POS warehouse before settling drinks.")
        if has_drinks and self.stock_warehouse_id:
            if self.stock_warehouse_id != warehouse.pk:
                raise ValidationError(
                    "The Bar/POS warehouse changed while this order was open. Clear or cancel the order."
                )
            if self.stock_warehouse.disabled:
                raise ValidationError("The order's Bar/POS warehouse snapshot is disabled.")
            return self.stock_warehouse
        self.stock_warehouse = warehouse if has_drinks else None
        return self.stock_warehouse

    @transaction.atomic
    def settle(self, payments_data, cashier=None, opening_entry=None):
        """Process a normal POS payment and submit the order atomically."""
        order = type(self).objects.select_for_update().get(pk=self.pk)
        if order.status != DRAFT:
            raise ValidationError("Order is already settled or cancelled.")
        if order.is_return:
            raise ValidationError("Return orders must use the deferred refund flow.")
        if not order.items.exists():
            raise ValidationError("Cannot settle an order with no items.")
        from apps.staff.models import POSOpeningEntry

        active_shift = (
            POSOpeningEntry.objects.select_for_update()
            .filter(pk=order.opening_entry_id, status=POSOpeningEntry.SUBMITTED, closing_entry__isnull=True)
            .first()
        )
        if active_shift is None:
            raise ValidationError("An active shift is required before settlement.")
        if opening_entry is not None and opening_entry.pk != active_shift.pk:
            raise ValidationError("This order does not belong to the active shift.")
        if cashier:
            order.cashier = cashier
        order.recalculate_totals()
        order.grand_total = order.rounded_total
        reservations_initialized = order._reservations_initialized()
        order._snapshot_stock_warehouse()
        order._validate_drink_stock_for_settlement(reservations_initialized=reservations_initialized)
        payment_rows = order._validate_payment_data(payments_data, active_shift)
        total_paid = sum((row["amount"] for row in payment_rows), Decimal("0"))
        if total_paid < order.grand_total:
            raise ValidationError("Payment must cover the full total.")
        if total_paid > order.grand_total and any(row["mode"].type != ModeOfPayment.TYPE_CASH for row in payment_rows):
            raise ValidationError("Only cash payments may include change.")
        if order.payments.exists():
            raise ValidationError("This draft already has payment rows and requires manager review.")

        if order.order_number is None:
            order.assign_order_number()
        order._settling = True
        try:
            for row in payment_rows:
                OrderPayment.objects.create(
                    order=order,
                    mode_of_payment=row["mode"],
                    amount=row["amount"],
                    reference_no=row["reference_no"],
                )
        finally:
            del order._settling

        order.paid_amount = total_paid
        order.change_amount = max(total_paid - order.grand_total, Decimal("0"))
        order.is_paid = True
        order.status = SUBMITTED
        order.submitted_at = timezone.now()
        order._allow_submit = True
        try:
            order.save()
        finally:
            del order._allow_submit
        order._convert_drink_reservations(reservations_initialized=reservations_initialized)
        order.audit("SUBMITTED", actor=cashier, metadata={"paid_amount": str(total_paid)})
        self.refresh_from_db()

    def _locked_drink_stock(self, *, reservations_initialized):
        drink_items = list(
            self.items.select_related("item")
            .filter(Q(department="DRINKS") | Q(department__isnull=True, item__department="DRINKS"))
            .order_by("item_id", "pk")
        )
        if not drink_items:
            return [], {}
        if not self.stock_warehouse_id:
            raise ValidationError("This order has no stock warehouse snapshot.")
        warehouse = self.stock_warehouse
        quantities = {}
        for order_item in drink_items:
            if not order_item.item.is_stock_item:
                raise ValidationError(f"{order_item.item_name} is a drink but is not configured as a stock item.")
            quantities[order_item.item_id] = quantities.get(order_item.item_id, Decimal("0")) + order_item.qty
        owned_quantities = quantities if reservations_initialized else {}
        bins = self._locked_drink_bins(quantities, warehouse)
        for item_id, qty in sorted(quantities.items()):
            bin_obj = bins[item_id]
            owned = owned_quantities.get(item_id, Decimal("0"))
            if bin_obj.reserved_qty < owned:
                raise ValidationError("Stock reservation data is inconsistent; manager review is required.")
            if bin_obj.actual_qty - bin_obj.reserved_qty + owned < qty:
                item = next(line.item for line in drink_items if line.item_id == item_id)
                raise ValidationError(f"Insufficient stock for {item.item_name} in {warehouse.name}.")
        return drink_items, bins

    def _validate_drink_stock_for_settlement(self, *, reservations_initialized):
        """Lock and recheck all drink stock before creating settlement side effects."""
        self._locked_drink_stock(reservations_initialized=reservations_initialized)

    def _convert_drink_reservations(self, *, reservations_initialized):
        """Atomically convert this order's drink reservations into stock ledger issues."""
        voucher_no = str(self.pk)
        drink_items, bins = self._locked_drink_stock(reservations_initialized=reservations_initialized)
        if not drink_items:
            return
        quantities = {}
        for order_item in drink_items:
            quantities[order_item.item_id] = quantities.get(order_item.item_id, Decimal("0")) + order_item.qty
        owned_quantities = quantities if reservations_initialized else {}
        for item_id in sorted(quantities):
            bin_obj = bins[item_id]
            owned = owned_quantities.get(item_id, Decimal("0"))
            bin_obj.reserved_qty -= owned
            bin_obj.save(update_fields=["reserved_qty", "updated_at"])
        for oi in drink_items:
            StockLedgerEntry._create_entry_locked(
                item=oi.item,
                warehouse=self.stock_warehouse,
                actual_qty=-oi.qty,
                voucher_type="POS Order",
                voucher_no=voucher_no,
                voucher_detail_no=str(oi.pk),
                prevent_negative=True,
                rate=Decimal("0"),
                bin_obj=bins[oi.item_id],
            )

    def _restore_stock(self):
        """Create positive stock ledger entries reversing a submitted order's deductions."""
        voucher_no = str(self.pk)
        stock_items = self.items.select_related("item").filter(
            Q(department="DRINKS") | Q(department__isnull=True, item__department="DRINKS")
        )
        if not stock_items.exists():
            return
        if not self.stock_warehouse_id:
            raise ValidationError("This order has no stock warehouse snapshot for reversal.")
        warehouse = self.stock_warehouse
        for oi in stock_items.only("item__is_stock_item", "qty"):
            StockLedgerEntry.create_entry(
                item=oi.item,
                warehouse=warehouse,
                actual_qty=oi.qty,
                voucher_type="POS Order Cancellation",
                voucher_no=voucher_no,
                voucher_detail_no=str(oi.pk),
            )

    def audit(self, event_type, actor=None, metadata=None):
        """Append an immutable order audit event."""
        return OrderAuditEvent.objects.create(
            order=self,
            event_type=event_type,
            actor=actor,
            metadata=metadata or {},
        )

    @transaction.atomic
    def cancel(self, reason, cancelled_by=None, reason_note=""):
        """Cancel an order through the immutable document workflow.

        Payment rows are preserved for audit — the cancelled order retains its
        original items, payments, and totals. Shift close (Phase 7) excludes
        cancelled orders by filtering on status != CANCELLED.
        """
        order = type(self).objects.select_for_update().get(pk=self.pk)
        if order.status == CANCELLED:
            self.refresh_from_db()
            return []
        if order.status == SUBMITTED and order.is_paid:
            raise ValidationError("Submitted paid orders cannot be cancelled; use the refund flow.")
        if not reason or not reason.strip():
            raise ValidationError("A cancel reason is required.")
        reason = reason.strip()
        reason_note = reason_note.strip()
        if reason not in dict(CANCEL_REASON_CHOICES):
            reason_note = reason_note or reason
            reason = CANCEL_REASON_OTHER
        order.cancel_reason = reason
        order.cancel_reason_note = reason_note
        order.cancelled_by = cancelled_by
        order.cancelled_at = timezone.now()
        if order.status == SUBMITTED:
            order._restore_stock()
        else:
            order._release_drink_reservations()
        cancellation_kots = order._cancel_kots()
        order.status = CANCELLED
        order._allow_cancellation = True
        try:
            order.save(
                update_fields=[
                    "status",
                    "cancel_reason",
                    "cancel_reason_note",
                    "cancelled_by",
                    "cancelled_at",
                    "updated_at",
                ]
            )
        finally:
            del order._allow_cancellation
        order.audit("CANCELLED", actor=cancelled_by, metadata={"reason": reason})
        self.refresh_from_db()
        return cancellation_kots

    @transaction.atomic
    def cancel_sent_order(self, reason, reason_note="", cancelled_by=None):
        """Cancel an unpaid draft — empty drafts can be abandoned, sent or printed orders cancelled."""
        order = type(self).objects.select_for_update().get(pk=self.pk)
        if order.status != DRAFT:
            raise ValidationError("Only draft orders can be cancelled from the POS.")
        if order.is_paid:
            raise ValidationError("Paid orders cannot be cancelled from the POS.")
        if order.items.exists() and not order.kots.exists() and not order.invoice_printed:
            raise ValidationError("Only a printed or sent order can be cancelled here.")
        if reason not in dict(CANCEL_REASON_CHOICES):
            raise ValidationError("Choose a valid cancellation reason.")

        order.status = CANCELLED
        order.cancel_reason = reason
        order.cancel_reason_note = reason_note.strip()
        order.cancelled_by = cancelled_by
        order.cancelled_at = timezone.now()
        order._release_drink_reservations()
        cancellation_kots = order._cancel_kots()
        order._allow_cancellation = True
        try:
            order.save(
                update_fields=[
                    "status",
                    "cancel_reason",
                    "cancel_reason_note",
                    "cancelled_by",
                    "cancelled_at",
                    "updated_at",
                ]
            )
        finally:
            del order._allow_cancellation
        order.audit(
            "CANCELLED",
            actor=cancelled_by,
            metadata={"reason": reason, "ticket_count": len(cancellation_kots)},
        )
        self.refresh_from_db()
        return cancellation_kots

    def _cancel_kots(self):
        """Create one cancellation KOT per station and close the source tickets."""
        active_kots = list(
            self.kots.filter(status=SUBMITTED, type=NEW_ORDER)
            .select_related("production_unit")
            .prefetch_related("items__item")
        )
        if not active_kots:
            return []
        created = []
        by_station = {}
        for original_kot in active_kots:
            station = by_station.setdefault(
                original_kot.production_unit_id,
                {"production_unit": original_kot.production_unit, "kots": [], "items": []},
            )
            station["kots"].append(original_kot)
            station["items"].extend(original_kot.items.all())

        for station in by_station.values():
            original_kots = station["kots"]
            production_unit = station["production_unit"]
            original_names = [kot.kot_number for kot in original_kots]
            ticket_type = original_kots[0].ticket_type
            kot = KOT.objects.create(
                order=self,
                production_unit=production_unit,
                type=KOT_CANCELLED,
                ticket_type=ticket_type,
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
                    item=ticket_item.item,
                    item_name=ticket_item.item_name,
                    qty=Decimal("0"),
                    cancelled_qty=abs(ticket_item.qty),
                    comments=ticket_item.comments,
                    customer_index=ticket_item.customer_index,
                )
                for ticket_item in station["items"]
            ]
            KOTItem.objects.bulk_create(kot_items)
            self.kots.filter(pk__in=[original.pk for original in original_kots]).update(
                status=CANCELLED,
                cancelled_by=self.cancelled_by_id,
                cancelled_at=timezone.now(),
                updated_at=timezone.now(),
            )
            created.append(kot)
        return created

    @transaction.atomic
    def make_return(self):
        """Create a manager-reviewed draft return with negative item quantities."""
        source = type(self).objects.select_for_update().prefetch_related("items", "payments").get(pk=self.pk)
        if source.status != SUBMITTED:
            raise ValidationError("Can only return submitted orders.")
        if source.is_return:
            raise ValidationError("Cannot return a return order.")
        if not source.is_paid:
            raise ValidationError("Only paid orders can be returned.")
        if source.return_orders.exclude(status=CANCELLED).exists():
            raise ValidationError("This order already has an active return.")

        return_order = Order.objects.create(
            order_type=source.order_type,
            customer_name=source.customer_name,
            guest_count=source.guest_count,
            cashier=source.cashier,
            opening_entry=source.opening_entry,
            is_return=True,
            return_against=source,
            stock_warehouse=source.stock_warehouse,
        )
        return_order.assign_order_number()
        for oi in source.items.all():
            OrderItem.objects.create(
                order=return_order,
                item=oi.item,
                item_name=oi.item_name,
                qty=-oi.qty,
                rate=oi.rate,
                department=oi.department,
                stock_item=oi.stock_item,
                customer_index=oi.customer_index,
                comments=oi.comments,
                menu_item=oi.menu_item,
                return_against_item=oi,
            )
        return_order.recalculate_totals()
        return_order.audit("RETURN_CREATED", actor=source.cashier, metadata={"source_order": source.pk})
        return return_order

    @transaction.atomic
    def create_tickets(self, created_by=None):
        """Create one immutable kitchen ticket and one bar ticket from the order snapshot."""
        order = type(self).objects.select_for_update().get(pk=self.pk)
        if order.status != DRAFT:
            raise ValidationError("Only draft orders can be sent to the kitchen or bar.")
        if order.kots.exists():
            raise ValidationError("This order has already been sent to the kitchen or bar.")
        if not order.items.exists():
            raise ValidationError("Add at least one item before sending the order.")

        if order.order_number is None:
            order.assign_order_number()

        from apps.settings.models import ProductionUnit

        items_by_department = {}
        for order_item in order.items.select_related("item"):
            department = order_item.department or order_item.item.department
            items_by_department.setdefault(department, []).append(order_item)
        production_units = {pu.department: pu for pu in ProductionUnit.objects.all()}
        planned_tickets = []
        missing_departments = []
        for department, order_items in items_by_department.items():
            production_unit = production_units.get(department)
            if order.order_type == TAKE_AWAY and production_unit and production_unit.block_takeaway_kot:
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
                order=order,
                production_unit=production_unit,
                type=NEW_ORDER,
                ticket_type=ticket_type,
                print_status=KOT_PRINT_PENDING,
                created_by=created_by,
                kot_number=f"TMP-{uuid4().hex}",
                order_number=order.order_number,
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

        order.audit("KOTS_CREATED", actor=created_by, metadata={"count": len(created)})
        return created


class OrderItem(BaseModel):
    """A single line item in an order."""

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="order_items")
    item_name = models.CharField(max_length=200)
    qty = models.DecimalField(max_digits=10, decimal_places=2)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    department = models.CharField(
        max_length=10,
        choices=[("FOOD", "Food"), ("DRINKS", "Drinks")],
        null=True,
        blank=True,
    )
    stock_item = models.BooleanField(null=True, blank=True, editable=False)
    customer_index = models.PositiveIntegerField(default=1)
    comments = models.CharField(max_length=200, blank=True)
    menu_item = models.ForeignKey("menu.MenuItem", on_delete=models.SET_NULL, null=True, blank=True)
    return_against_item = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="return_items",
    )

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(qty__gt=0) | Q(return_against_item__isnull=False),
                name="orders_item_qty_valid",
            ),
            models.CheckConstraint(condition=Q(rate__gte=0), name="orders_item_rate_gte_zero"),
            models.CheckConstraint(condition=Q(customer_index__gte=1), name="orders_item_customer_gte_one"),
        ]

    def __str__(self):
        return f"{self.item_name}"

    def _validate_return_line(self, order):
        if not order.is_return:
            if self.return_against_item_id:
                raise ValidationError("Only return lines may reference an original order item.")
            return
        if not self.return_against_item_id:
            raise ValidationError("A return line must reference an original order item.")
        if self.qty >= 0:
            raise ValidationError("Return quantities must be negative.")

        source_item = type(self).objects.select_related("order").filter(pk=self.return_against_item_id).first()
        if source_item is None or source_item.order_id != order.return_against_id:
            raise ValidationError("Return line must reference an item from the original order.")
        if source_item.qty <= 0:
            raise ValidationError("Only positive quantities from the original order can be returned.")

        returned_query = (
            type(self)
            .objects.filter(
                return_against_item_id=source_item.pk,
                order__is_return=True,
            )
            .exclude(order__status=CANCELLED)
        )
        if self.pk:
            returned_query = returned_query.exclude(pk=self.pk)
        returned_total = returned_query.aggregate(total=Sum("qty"))["total"] or Decimal("0")
        if abs(returned_total) + abs(self.qty) > source_item.qty:
            raise ValidationError("Return quantity cannot exceed the quantity sold on the original order.")

    def clean(self):
        super().clean()
        if self.order_id:
            order = Order.objects.get(pk=self.order_id)
            self._validate_return_line(order)

    def save(self, *args, **kwargs):
        if self.order_id:
            order = Order.objects.get(pk=self.order_id)
            order._ensure_editable()
            self._validate_return_line(order)
        if not self.item_name and self.item_id:
            self.item_name = self.item.item_name
        if self.item_id and not self.department:
            self.department = self.item.department
        if self.item_id and self.stock_item is None:
            self.stock_item = self.item.is_stock_item
        try:
            qty = Decimal(str(self.qty))
            rate = Decimal(str(self.rate))
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise ValidationError("Quantity and rate must be valid decimals.") from exc
        if not qty.is_finite() or not rate.is_finite() or rate < 0:
            raise ValidationError("Quantity and rate must be finite; rate cannot be negative.")
        if self.order.is_return:
            if qty >= 0:
                raise ValidationError("Return quantities must be negative.")
        elif qty <= 0:
            raise ValidationError("Quantity must be greater than zero.")
        self.qty = qty
        self.rate = rate
        self.amount = (self.qty * self.rate).quantize(TWO_PLACES)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.order_id:
            order = Order.objects.get(pk=self.order_id)
            order._ensure_editable()
        return super().delete(*args, **kwargs)


class OrderPayment(BaseModel):
    """A payment line within an order."""

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    mode_of_payment = models.ForeignKey(ModeOfPayment, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference_no = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="orders_payment_amount_gt_zero"),
            models.UniqueConstraint(
                fields=["mode_of_payment", "reference_no"],
                condition=~Q(reference_no=""),
                name="orders_payment_reference_unique",
            ),
        ]

    def __str__(self):
        return f"{self.mode_of_payment.name}: {self.amount}"

    def save(self, *args, **kwargs):
        try:
            amount = Decimal(str(self.amount))
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise ValidationError("Payment amount must be a valid decimal.") from exc
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(TWO_PLACES):
            raise ValidationError("Payment amount must be finite and greater than zero.")
        self.amount = amount
        self.reference_no = (self.reference_no or "").strip()
        if self.mode_of_payment_id:
            mode = (
                self.mode_of_payment
                if hasattr(self, "mode_of_payment")
                else ModeOfPayment.objects.get(pk=self.mode_of_payment_id)
            )
            if mode.type != ModeOfPayment.TYPE_CASH and self.reference_no:
                duplicate = (
                    OrderPayment.objects.filter(
                        mode_of_payment_id=self.mode_of_payment_id,
                        reference_no=self.reference_no,
                    )
                    .exclude(pk=self.pk)
                    .exists()
                )
                if duplicate:
                    raise ValidationError("This electronic payment reference has already been used.")
        order = self.order if self.order_id else None
        if not order or not getattr(order, "_settling", False):
            order = Order.objects.only("status", "invoice_printed").get(pk=self.order_id)
            if order.status != DRAFT:
                raise ValidationError("Payments on submitted or cancelled orders cannot be modified.")
            if order.invoice_printed or order.kots.exists():
                raise ValidationError("Payments cannot be edited after a receipt or KOT has been created.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        order = Order.objects.only("status", "invoice_printed").get(pk=self.order_id)
        if order.status != DRAFT:
            raise ValidationError("Payments on submitted or cancelled orders cannot be deleted.")
        if order.invoice_printed or order.kots.exists():
            raise ValidationError("Payments cannot be deleted after a receipt or KOT has been created.")
        return super().delete(*args, **kwargs)


class KOT(BaseModel):
    """Kitchen Order Ticket — immutable once generated."""

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="kots")
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
    cancelled_by = models.ForeignKey(
        "users.CustomUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="cancelled_kots"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-posting_datetime"]
        indexes = [models.Index(fields=["status", "print_status", "-posting_datetime"])]

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

    kot = models.ForeignKey(KOT, on_delete=models.PROTECT, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    item_name = models.CharField(max_length=200)
    qty = models.DecimalField(max_digits=10, decimal_places=2)
    cancelled_qty = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    comments = models.CharField(max_length=200, blank=True)
    customer_index = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=Q(qty__gte=0), name="orders_kot_item_qty_gte_zero"),
            models.CheckConstraint(condition=Q(cancelled_qty__gte=0), name="orders_kot_cancelled_qty_gte_zero"),
            models.CheckConstraint(condition=Q(customer_index__gte=1), name="orders_kot_customer_gte_one"),
        ]

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


class OrderAuditEvent(BaseModel):
    """Immutable audit event for an order lifecycle or mutation."""

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="audit_events")
    event_type = models.CharField(max_length=50)
    actor = models.ForeignKey(
        "users.CustomUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="order_audit_events"
    )
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["created_at", "pk"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Order audit events cannot be edited.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Order audit events cannot be deleted.")

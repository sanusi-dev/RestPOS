from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
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
DELIVERY = "DELIVERY"
PHONE_IN = "PHONE_IN"
ORDER_TYPE_CHOICES = [
    (DINE_IN, "Dine In"),
    (TAKE_AWAY, "Take Away"),
    (DELIVERY, "Delivery"),
    (PHONE_IN, "Phone In"),
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


class Order(BaseModel):
    """A POS order — the single source of truth for items, payments, taxes, and status."""

    invoice_number = models.CharField(max_length=50, unique=True, editable=False)
    order_type = models.CharField(max_length=20, choices=ORDER_TYPE_CHOICES, default=DINE_IN)
    restaurant = models.ForeignKey("settings.Restaurant", on_delete=models.PROTECT, related_name="orders")
    branch = models.ForeignKey("settings.Branch", on_delete=models.PROTECT, related_name="orders")
    pos_profile = models.ForeignKey("settings.POSProfile", on_delete=models.PROTECT, null=True, blank=True)
    table = models.ForeignKey("settings.Table", on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    room = models.ForeignKey("settings.Room", on_delete=models.SET_NULL, null=True, blank=True)
    customer_name = models.CharField(max_length=200, default="Walk-in Customer")
    customer_mobile = models.CharField(max_length=20, blank=True)
    guest_count = models.PositiveIntegerField(default=1)
    waiter = models.ForeignKey("users.CustomUser", on_delete=models.SET_NULL, null=True, blank=True)
    cashier = models.ForeignKey(
        "users.CustomUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="settled_orders"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    is_paid = models.BooleanField(default=False)
    invoice_printed = models.BooleanField(default=False)
    posting_date = models.DateField(default=timezone.now)
    posting_time = models.TimeField(default=timezone.now)
    net_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
    total_taxes = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
    rounded_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
    change_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    outstanding_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    comments = models.TextField(blank=True)
    cancel_reason = models.TextField(blank=True)
    taxes_and_charges_template = models.ForeignKey(
        "settings.TaxTemplate", on_delete=models.SET_NULL, null=True, blank=True
    )
    amended_from = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True)
    opening_entry = models.ForeignKey(
        "staff.POSOpeningEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    order_number = models.PositiveIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-posting_date", "-posting_time"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["posting_date"]),
            models.Index(fields=["branch"]),
        ]

    def __str__(self):
        return f"{self.invoice_number} - {self.customer_name}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if not self.restaurant_id:
            from apps.settings.models import POSProfile

            profile = POSProfile.objects.select_related("restaurant", "restaurant__branch").first()
            if profile:
                self.restaurant = profile.restaurant
                self.branch = profile.restaurant.branch
                self.pos_profile = profile
        if self.table_id and (is_new or self._table_changed()):
            self.room = self.table.room
        if self.branch_id and not self.restaurant_id:
            self.restaurant = self.branch.restaurants.first()
        super().save(*args, **kwargs)
        if is_new and not self.invoice_number:
            prefix = self.restaurant.invoice_series_prefix if self.restaurant_id else "REST-"
            self.invoice_number = f"{prefix}{self.pk}"
            super().save(update_fields=["invoice_number"])

    def _table_changed(self):
        if not self.pk:
            return True
        try:
            original = Order.objects.only("table_id").get(pk=self.pk)
        except Order.DoesNotExist:
            return True
        return original.table_id != self.table_id

    def clean(self):
        super().clean()
        if self.table_id and self.order_type == DINE_IN:
            if self.pk:
                existing = Order.objects.filter(table=self.table, status=DRAFT).exclude(pk=self.pk).exists()
            else:
                existing = Order.objects.filter(table=self.table, status=DRAFT).exists()
            if existing:
                raise ValidationError({"table": "This table already has an open order."})
        if self.status == CANCELLED and not self.cancel_reason:
            raise ValidationError({"cancel_reason": "A cancel reason is required."})

    def recalculate_totals(self):
        total = self.items.aggregate(t=models.Sum("amount"))["t"] or Decimal("0")
        self.net_total = total
        self.save(update_fields=["net_total", "updated_at"])

    def add_item(self, item, qty=1, customer_index=1, comments="", rate=None):
        if self.status != DRAFT:
            raise ValidationError("Cannot modify a submitted order.")
        existing = self.items.filter(item=item, customer_index=customer_index).first()
        if existing:
            existing.qty += qty
            existing.comments = comments or existing.comments
            existing.save()
            return existing
        order_item = OrderItem.objects.create(
            order=self, item=item, qty=qty, customer_index=customer_index, comments=comments, rate=rate or Decimal("0")
        )
        self.recalculate_totals()
        return order_item

    def remove_item(self, order_item_pk):
        if self.status != DRAFT:
            raise ValidationError("Cannot modify a submitted order.")
        self.items.filter(pk=order_item_pk).delete()
        self.recalculate_totals()

    def clear_items(self):
        if self.status != DRAFT:
            raise ValidationError("Cannot modify a submitted order.")
        self.items.all().delete()
        self.recalculate_totals()

    def calculate_taxes(self):
        template = self.taxes_and_charges_template
        if self.restaurant_id and not template:
            template = self.restaurant.default_tax_template
        self.taxes.all().delete()
        if not template:
            return Decimal("0")
        from apps.settings.models import TaxRate

        net_total = self.net_total
        previous_total = Decimal("0")
        previous_amount = Decimal("0")
        total_tax = Decimal("0")
        for rate_row in template.rates.order_by("pk"):
            tax_amount = Decimal("0")
            if rate_row.charge_type == TaxRate.ON_NET_TOTAL:
                tax_amount = (net_total * rate_row.rate / 100).quantize(Decimal("0.01"))
            elif rate_row.charge_type == TaxRate.ACTUAL:
                tax_amount = rate_row.rate
            elif rate_row.charge_type == TaxRate.ON_PREVIOUS_ROW_AMOUNT:
                tax_amount = (previous_amount * rate_row.rate / 100).quantize(Decimal("0.01"))
            elif rate_row.charge_type == TaxRate.ON_PREVIOUS_ROW_TOTAL:
                tax_amount = (previous_total * rate_row.rate / 100).quantize(Decimal("0.01"))
            if tax_amount > 0:
                OrderTax.objects.create(
                    order=self,
                    description=rate_row.description,
                    charge_type=rate_row.charge_type,
                    rate=rate_row.rate,
                    tax_amount=tax_amount,
                    account_head=rate_row.account_head,
                )
                total_tax += tax_amount
                previous_amount = tax_amount
                previous_total = net_total + total_tax
        self.total_taxes = total_tax
        return total_tax

    def apply_discount(self, discount_percentage, discount_on):
        if not discount_percentage:
            return
        percentage = Decimal(str(discount_percentage))
        if discount_on == "GRAND_TOTAL":
            self.discount_amount = (self.grand_total * percentage / 100).quantize(Decimal("0.01"))
        else:
            self.discount_amount = (self.net_total * percentage / 100).quantize(Decimal("0.01"))

    def settle(self, payments_data, cashier=None, discount_percentage=None, discount_on="GRAND_TOTAL"):
        if self.status != DRAFT:
            raise ValidationError("Order is already settled or cancelled.")
        if cashier:
            self.cashier = cashier
        total_tax = self.calculate_taxes()
        self.grand_total = self.net_total + total_tax
        if discount_percentage:
            self.apply_discount(discount_percentage, discount_on)
        self.rounded_total = (round(self.grand_total - self.discount_amount, 0)).quantize(Decimal("1"))
        self.grand_total = self.rounded_total
        self.payments.all().delete()
        total_paid = Decimal("0")
        for entry in payments_data:
            mode_pk = entry.get("mode_of_payment") or entry.get("mode_of_payment_id")
            amount = Decimal(str(entry.get("amount", 0)))
            ref = entry.get("reference_no", "")
            OrderPayment.objects.create(order=self, mode_of_payment_id=mode_pk, amount=amount, reference_no=ref)
            total_paid += amount
        self.paid_amount = total_paid
        if total_paid > self.grand_total:
            self.change_amount = total_paid - self.grand_total
        else:
            self.outstanding_amount = self.grand_total - total_paid
        self.is_paid = True
        self.status = SUBMITTED
        self.save()
        self._deduct_stock()
        if self.table and self.order_type == DINE_IN:
            self.table.occupied = False
            self.table.latest_invoice_time = timezone.now()
            self.table.save(update_fields=["occupied", "latest_invoice_time", "updated_at"])

    def _deduct_stock(self):
        voucher_no = str(self.pk)
        for item in self.items.select_related("item").all():
            if not item.item.is_stock_item:
                continue
            warehouse = self.pos_profile.warehouse if self.pos_profile else item.item.default_warehouse
            if not warehouse:
                continue
            StockLedgerEntry.create_entry(
                item=item.item,
                warehouse=warehouse,
                actual_qty=-item.qty,
                voucher_type="POS Order",
                voucher_no=voucher_no,
                voucher_detail_no=str(item.pk),
            )

    def submit(self):
        if self.status != DRAFT:
            return
        self._deduct_stock()
        if self.table and self.order_type == DINE_IN:
            self.table.occupied = False
            self.table.latest_invoice_time = timezone.now()
            self.table.save(update_fields=["occupied", "latest_invoice_time", "updated_at"])
        self.status = SUBMITTED
        self.is_paid = True
        self.save(update_fields=["status", "is_paid", "updated_at"])

    def cancel(self, reason):
        if self.status == CANCELLED:
            return
        self.cancel_reason = reason or self.cancel_reason
        if self.status == SUBMITTED:
            voucher_no = str(self.pk)
            for item in self.items.select_related("item").all():
                if not item.item.is_stock_item:
                    continue
                warehouse = self.pos_profile.warehouse if self.pos_profile else item.item.default_warehouse
                if not warehouse:
                    continue
                StockLedgerEntry.create_entry(
                    item=item.item,
                    warehouse=warehouse,
                    actual_qty=item.qty,
                    voucher_type="POS Order Cancellation",
                    voucher_no=voucher_no,
                    voucher_detail_no=str(item.pk),
                )
        if self.table:
            self.table.occupied = False
            self.table.latest_invoice_time = timezone.now()
            self.table.save(update_fields=["occupied", "latest_invoice_time", "updated_at"])
        self.status = CANCELLED
        self.save(update_fields=["status", "cancel_reason", "updated_at"])

    def generate_kots(self, previous_items_state):
        current = {
            (oi.item_id, oi.customer_index, oi.comments or ""): oi.qty for oi in self.items.select_related("item").all()
        }
        previous = {}
        for pi in previous_items_state:
            key = (pi["item_id"], pi.get("customer_index", 1), pi.get("comments", ""))
            previous[key] = Decimal(str(pi["qty"]))

        new_or_increased = {}
        removed_or_decreased = {}

        for key, new_qty in current.items():
            old_qty = previous.get(key, Decimal("0"))
            if new_qty > old_qty:
                new_or_increased[key] = new_qty - old_qty
            elif new_qty < old_qty:
                removed_or_decreased[key] = old_qty - new_qty
        for key, old_qty in previous.items():
            if key not in current:
                removed_or_decreased[key] = old_qty

        kot_name = self.pos_profile.kot_naming_series if self.pos_profile else "KOT-####"
        branch = self.branch
        production_units = {}
        from apps.settings.models import ProductionUnit

        for pu in ProductionUnit.objects.filter(branch=branch).select_related("pos_profile"):
            production_units[pu.department] = pu

        if new_or_increased:
            for pu_department, pu in production_units.items():
                items_for_unit = []
                for (item_id, customer_index, comments), qty in new_or_increased.items():
                    item = Item.objects.only("department").get(pk=item_id)
                    if item.department == pu_department:
                        items_for_unit.append((item_id, customer_index, comments, qty))
                if not items_for_unit:
                    continue
                existing_kot = (
                    self.kots.filter(production_unit=pu, status=SUBMITTED)
                    .exclude(type__in=[KOT_CANCELLED, PARTIALLY_CANCELLED])
                    .first()
                )
                kot_type = ORDER_MODIFIED if existing_kot else NEW_ORDER
                kot = KOT.objects.create(
                    order=self,
                    production_unit=pu,
                    type=kot_type,
                    naming_series=kot_name,
                    branch=branch,
                    status=SUBMITTED,
                )
                kot.kot_number = f"KOT-{kot.pk:04d}"
                kot.save(update_fields=["kot_number"])
                for item_id, customer_index, comments, qty in items_for_unit:
                    item = Item.objects.only("item_name").get(pk=item_id)
                    KOTItem.objects.create(
                        kot=kot,
                        item_id=item_id,
                        item_name=item.item_name,
                        qty=qty,
                        comments=comments,
                        customer_index=customer_index,
                    )

        if removed_or_decreased:
            for pu_department, pu in production_units.items():
                items_for_unit = []
                for (item_id, customer_index, comments), qty in removed_or_decreased.items():
                    item = Item.objects.only("department").get(pk=item_id)
                    if item.department == pu_department:
                        items_for_unit.append((item_id, customer_index, comments, qty))
                if not items_for_unit:
                    continue
                original_kot_names = (
                    self.kots.filter(production_unit=pu, status=SUBMITTED)
                    .exclude(type__in=[KOT_CANCELLED, PARTIALLY_CANCELLED])
                    .values_list("kot_number", flat=True)
                )
                kot = KOT.objects.create(
                    order=self,
                    production_unit=pu,
                    type=PARTIALLY_CANCELLED,
                    naming_series=f"CNCL-{kot_name}",
                    branch=branch,
                    status=SUBMITTED,
                    original_kots=",".join(original_kot_names),
                )
                kot.kot_number = f"CNCL-KOT-{kot.pk:04d}"
                kot.save(update_fields=["kot_number"])
                for item_id, customer_index, comments, qty in items_for_unit:
                    item = Item.objects.only("item_name").get(pk=item_id)
                    KOTItem.objects.create(
                        kot=kot,
                        item_id=item_id,
                        item_name=item.item_name,
                        qty=Decimal("0"),
                        cancelled_qty=qty,
                        comments=comments,
                        customer_index=customer_index,
                    )


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
    department = models.CharField(max_length=10, choices=[("FOOD", "Food"), ("DRINKS", "Drinks")])
    uom = models.ForeignKey("inventory.UOM", on_delete=models.PROTECT)
    price_list = models.ForeignKey("menu.PriceList", on_delete=models.SET_NULL, null=True, blank=True)
    menu_item = models.ForeignKey("menu.MenuItem", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.item_name} x{self.qty}"

    def save(self, *args, **kwargs):
        if not self.item_name and self.item_id:
            self.item_name = self.item.item_name
        if not self.department and self.item_id:
            self.department = self.item.department
        if not self.uom_id and self.item_id:
            self.uom = self.item.stock_uom
        if self.rate is None:
            self.rate = Decimal("0")
        self.amount = (self.qty * self.rate).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)


class OrderPayment(BaseModel):
    """A payment line within an order."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    mode_of_payment = models.ForeignKey(ModeOfPayment, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference_no = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.mode_of_payment.name}: {self.amount}"


class OrderTax(BaseModel):
    """A computed tax line on an order."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="taxes")
    description = models.CharField(max_length=255)
    charge_type = models.CharField(max_length=30)
    rate = models.DecimalField(max_digits=8, decimal_places=4)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2)
    account_head = models.CharField(max_length=200)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.description}: {self.tax_amount}"


class KOT(BaseModel):
    """Kitchen Order Ticket — immutable once generated."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="kots")
    production_unit = models.ForeignKey("settings.ProductionUnit", on_delete=models.PROTECT, related_name="kots")
    type = models.CharField(max_length=25, choices=KOT_TYPE_CHOICES)
    naming_series = models.CharField(max_length=50)
    kot_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(
        max_length=15,
        choices=[(SUBMITTED, "Submitted"), (CANCELLED, "Cancelled")],
        default=SUBMITTED,
    )
    posting_datetime = models.DateTimeField(auto_now_add=True)
    branch = models.ForeignKey("settings.Branch", on_delete=models.PROTECT)
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

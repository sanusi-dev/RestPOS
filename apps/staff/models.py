from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.payments.models import ModeOfPayment
from apps.users.models import CustomUser
from apps.utils.models import BaseModel


class POSOpeningEntry(BaseModel):
    """Start-of-shift document. One OPEN shift at a time."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"
    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (SUBMITTED, "Submitted"),
        (CANCELLED, "Cancelled"),
    ]

    period_start_date = models.DateTimeField(default=timezone.now, editable=False)
    period_end_date = models.DateTimeField(null=True, blank=True, editable=False)
    posting_date = models.DateField(default=timezone.localdate)
    cashier = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        related_name="pos_opening_entries",
    )
    closing_entry = models.OneToOneField(
        "staff.POSClosingEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opening_entry_ref",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    remarks = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_opening_entries",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-period_start_date"]
        indexes = [models.Index(fields=["status", "period_start_date"])]

    def __str__(self):
        return f"Opening #{self.pk} — {self.posting_date}"

    def clean(self):
        super().clean()
        # Enforce "one Open shift". The check must fire whenever this entry is
        # on the way to becoming Open — i.e. either it is already SUBMITTED
        # (cleanup/edit), or it is DRAFT but about to be submitted (the view
        # calls `full_clean()` before `submit()` flips the status, so guarding
        # on `status == SUBMITTED` alone misses the submit path entirely).
        is_open_or_will_open = self.status == self.SUBMITTED and self.closing_entry_id is None
        is_being_submitted = self.status == self.DRAFT
        if is_open_or_will_open or is_being_submitted:
            qs = POSOpeningEntry.objects.filter(
                status=self.SUBMITTED,
                closing_entry__isnull=True,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    "An open shift already exists. Close the existing shift before opening a new one."
                )

    @property
    def is_open(self):
        return self.status == self.SUBMITTED and self.closing_entry_id is None

    @property
    def is_closed(self):
        return self.status == self.SUBMITTED and self.closing_entry_id is not None

    def submit(self):
        """Transition from DRAFT to SUBMITTED. Idempotent.

        Also re-runs the "one Open shift" check inside a `select_for_update`
        transaction — closes the race between two concurrent POSTs that both
        pass `full_clean()` before either flips to SUBMITTED. The view calls
        `full_clean()` first; this is the last line of defense.
        """
        if self.status != self.DRAFT:
            return
        with transaction.atomic():
            from apps.settings.models import Restaurant

            Restaurant.objects.select_for_update().first()
            open_exists = (
                POSOpeningEntry.objects.select_for_update()
                .filter(
                    status=self.SUBMITTED,
                    closing_entry__isnull=True,
                )
                .exclude(pk=self.pk)
                .exists()
            )
            if open_exists:
                raise ValidationError(
                    "An open shift already exists. Close the existing shift before opening a new one."
                )
            self.status = self.SUBMITTED
            self.save(update_fields=["status", "updated_at"])

    def cancel(self, by_user=None):
        """Cancel a draft or open shift. Closed shifts cannot be cancelled."""
        if self.status == self.CANCELLED:
            return
        if self.closing_entry_id is not None:
            raise ValidationError(
                "Cannot cancel a shift that has already been closed. Cancel the closing entry instead."
            )
        self.status = self.CANCELLED
        self.cancelled_at = timezone.now()
        if by_user is not None:
            self.cancelled_by = by_user
        self.save(update_fields=["status", "cancelled_at", "cancelled_by", "updated_at"])


class OpeningPayment(BaseModel):
    """Child row: opening float per payment method at shift-open time."""

    opening_entry = models.ForeignKey(
        POSOpeningEntry,
        on_delete=models.CASCADE,
        related_name="opening_payments",
    )
    mode_of_payment = models.ForeignKey(
        ModeOfPayment,
        on_delete=models.PROTECT,
        related_name="opening_payments",
    )
    opening_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        unique_together = [("opening_entry", "mode_of_payment")]
        ordering = ["mode_of_payment__name"]

    def __str__(self):
        return f"{self.mode_of_payment.name}: {self.opening_amount}"


class POSClosingEntry(BaseModel):
    """End-of-shift reconciliation document. Links to a POSOpeningEntry."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"
    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (SUBMITTED, "Submitted"),
        (CANCELLED, "Cancelled"),
    ]

    opening_entry = models.OneToOneField(
        POSOpeningEntry,
        on_delete=models.PROTECT,
        related_name="closing_entry_for",
    )
    period_start_date = models.DateTimeField(editable=False)
    period_end_date = models.DateTimeField(default=timezone.now)
    posting_date = models.DateField(default=timezone.localdate)
    cashier = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        related_name="pos_closing_entries",
    )
    total_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    net_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
    total_short_excess = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    remarks = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_closing_entries",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-period_end_date"]

    def __str__(self):
        return f"Closing #{self.pk} — {self.posting_date}"

    def save(self, *args, **kwargs):
        # Auto-fill period_start / posting_date / cashier from the linked
        # opening on the first save. Skipped if explicitly overridden.
        if self.opening_entry_id and self.period_start_date is None:
            self.period_start_date = self.opening_entry.period_start_date
        if self.opening_entry_id and not self.cashier_id:
            self.cashier_id = self.opening_entry.cashier_id
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.opening_entry_id and not self.opening_entry.is_open:
            raise ValidationError(
                {
                    "opening_entry": (
                        "This opening entry is not open — it is already closed, cancelled, or still in draft."
                    )
                }
            )

    @transaction.atomic
    def submit(self):
        """Compute expected amounts, validate, and close the opening entry."""
        if self.status != self.DRAFT:
            return
        closing = type(self).objects.select_for_update().select_related("opening_entry").get(pk=self.pk)
        opening = POSOpeningEntry.objects.select_for_update().get(pk=closing.opening_entry_id)
        if not opening.is_open:
            raise ValidationError("The opening shift is no longer open.")
        opening_modes = {
            op.mode_of_payment_id: op for op in opening.opening_payments.select_related("mode_of_payment").all()
        }
        from apps.orders.models import DRAFT, SUBMITTED, Order, OrderPayment  # noqa: I001

        draft_count = Order.objects.filter(opening_entry=opening, status=DRAFT, is_return=False).count()
        if draft_count:
            raise ValidationError(
                f"Close or settle {draft_count} open order{'s' if draft_count != 1 else ''} before closing the shift."
            )

        submitted_orders = Order.objects.filter(
            opening_entry=opening,
            status=SUBMITTED,
            is_return=False,
            submitted_at__gte=closing.period_start_date,
            submitted_at__lte=closing.period_end_date,
        )
        closing.total_quantity = submitted_orders.aggregate(total=Sum("items__qty"))["total"] or Decimal("0")
        closing.net_total = submitted_orders.aggregate(total=Sum("net_total"))["total"] or Decimal("0")
        closing.grand_total = submitted_orders.aggregate(total=Sum("grand_total"))["total"] or Decimal("0")

        for cp in closing.closing_payments.select_related("mode_of_payment").all():
            if cp.mode_of_payment_id not in opening_modes:
                raise ValidationError({"mode_of_payment": (f"{cp.mode_of_payment} was not declared at shift open.")})
            cp.opening_amount = opening_modes[cp.mode_of_payment_id].opening_amount
            payment_total = OrderPayment.objects.filter(
                order__in=submitted_orders,
                mode_of_payment_id=cp.mode_of_payment_id,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
            if cp.mode_of_payment.type == ModeOfPayment.TYPE_CASH:
                change_total = sum(
                    (
                        order.change_amount
                        for order in submitted_orders.filter(
                            payments__mode_of_payment_id=cp.mode_of_payment_id
                        ).distinct()
                    ),
                    Decimal("0"),
                )
                payment_total -= change_total
            cp.expected_amount = cp.opening_amount + payment_total
            cp.difference = cp.closing_amount - cp.expected_amount
            cp.save(
                update_fields=[
                    "opening_amount",
                    "expected_amount",
                    "difference",
                    "updated_at",
                ]
            )
        closing.total_short_excess = sum(
            (cp.difference for cp in closing.closing_payments.all()),
            Decimal("0"),
        )
        closing.status = closing.SUBMITTED
        closing.save(
            update_fields=[
                "total_quantity",
                "net_total",
                "grand_total",
                "total_short_excess",
                "status",
                "updated_at",
            ]
        )
        # Flip the opening entry to Closed
        opening.closing_entry = closing
        opening.period_end_date = closing.period_end_date
        opening.save(update_fields=["closing_entry", "period_end_date", "updated_at"])
        self.refresh_from_db()

    def cancel(self, by_user=None):
        """Cancel a closing entry. Blocked if a new Open shift exists."""
        if self.status == self.CANCELLED:
            return
        new_open_exists = (
            POSOpeningEntry.objects.filter(
                status=self.SUBMITTED,
                closing_entry__isnull=True,
            )
            .exclude(pk=self.opening_entry_id)
            .exists()
        )
        if new_open_exists:
            raise ValidationError(
                "Cannot cancel this closing entry — a new shift is open. Close or cancel the new shift first."
            )
        self.status = self.CANCELLED
        self.cancelled_at = timezone.now()
        if by_user is not None:
            self.cancelled_by = by_user
        self.save(update_fields=["status", "cancelled_at", "cancelled_by", "updated_at"])


class ClosingPayment(BaseModel):
    """Child row: one per payment method, with opening/expected/closing/difference."""

    closing_entry = models.ForeignKey(
        POSClosingEntry,
        on_delete=models.CASCADE,
        related_name="closing_payments",
    )
    mode_of_payment = models.ForeignKey(
        ModeOfPayment,
        on_delete=models.PROTECT,
        related_name="closing_payments",
    )
    opening_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)
    closing_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    difference = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), editable=False)

    class Meta:
        unique_together = [("closing_entry", "mode_of_payment")]
        ordering = ["mode_of_payment__name"]

    def __str__(self):
        return f"{self.mode_of_payment.name}: closing {self.closing_amount} / expected {self.expected_amount}"

    def clean(self):
        super().clean()
        if self.closing_entry_id and self.mode_of_payment_id:
            valid_modes = set(
                self.closing_entry.opening_entry.opening_payments.values_list("mode_of_payment_id", flat=True)
            )
            if self.mode_of_payment_id not in valid_modes:
                raise ValidationError({"mode_of_payment": (f"{self.mode_of_payment} was not declared at shift open.")})

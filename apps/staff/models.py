from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
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

    def submit(self):
        """Compute expected amounts, validate, and close the opening entry."""
        if self.status != self.DRAFT:
            return
        opening_modes = {op.mode_of_payment_id: op for op in self.opening_entry.opening_payments.all()}
        for cp in self.closing_payments.all():
            if cp.mode_of_payment_id not in opening_modes:
                raise ValidationError({"mode_of_payment": (f"{cp.mode_of_payment} was not declared at shift open.")})
            cp.opening_amount = opening_modes[cp.mode_of_payment_id].opening_amount
            # Phase 5: expected_amount = opening_amount only. Phase 7 will add
            # + sum(OrderPayment) for the same method.
            # TODO(Phase 7): filter to orders within this shift's window where
            # status=SUBMITTED and is_return=False. Cancelled orders already have
            # status=CANCELLED and won't match status=SUBMITTED. Return orders
            # refund cash and must not add to expected drawer amounts.
            cp.expected_amount = cp.opening_amount
            cp.difference = cp.closing_amount - cp.expected_amount
            cp.save(
                update_fields=[
                    "opening_amount",
                    "expected_amount",
                    "difference",
                    "updated_at",
                ]
            )
        self.total_short_excess = sum(
            (cp.difference for cp in self.closing_payments.all()),
            Decimal("0"),
        )
        self.status = self.SUBMITTED
        self.save(
            update_fields=[
                "total_short_excess",
                "status",
                "updated_at",
            ]
        )
        # Flip the opening entry to Closed
        self.opening_entry.closing_entry = self
        self.opening_entry.period_end_date = self.period_end_date
        self.opening_entry.save(update_fields=["closing_entry", "period_end_date", "updated_at"])

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

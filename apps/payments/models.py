from django.core.exceptions import ValidationError
from django.db import models

from apps.settings.models import Restaurant
from apps.utils.models import BaseModel


class ModeOfPayment(BaseModel):
    """A payment method the restaurant accepts."""

    TYPE_CASH = "CASH"
    TYPE_BANK = "BANK"
    TYPE_GENERAL = "GENERAL"
    TYPE_PHONE = "PHONE"
    TYPE_CHOICES = [
        (TYPE_CASH, "Cash"),
        (TYPE_BANK, "Bank"),
        (TYPE_GENERAL, "General"),
        (TYPE_PHONE, "Phone"),
    ]

    name = models.CharField(max_length=50, unique=True)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def can_dispense_change(self):
        """Return True if this payment mode can dispense physical change."""
        return self.type == self.TYPE_CASH


class PaymentGLMapping(BaseModel):
    """Maps a ModeOfPayment to a General Ledger account name."""

    mode_of_payment = models.ForeignKey(
        ModeOfPayment,
        on_delete=models.PROTECT,
        related_name="gl_mappings",
    )
    company = models.CharField(max_length=200)
    default_account = models.CharField(max_length=200)

    class Meta:
        unique_together = [("mode_of_payment", "company")]
        ordering = ["mode_of_payment__name", "company"]

    def __str__(self):
        return f"{self.mode_of_payment.name} → {self.default_account}"

    def clean(self):
        super().clean()
        # The company field defaults from the (single) Restaurant singleton in
        # `__init__` / `save()` — at this point the field has already been
        # validated for blank. We only validate the dependent field here.
        if self.mode_of_payment_id and not self.default_account:
            raise ValidationError({"default_account": "A default GL account name is required for the mapping."})

    def save(self, *args, **kwargs):
        if not self.company:
            first = Restaurant.objects.first()
            if first is not None and first.company:
                self.company = first.company
        super().save(*args, **kwargs)

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

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
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="payments_one_default_mode",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.is_default:
            clash = ModeOfPayment.objects.filter(is_default=True).exclude(pk=self.pk).exists()
            if clash:
                raise ValidationError({"is_default": "Another payment method is already the default."})

    @property
    def can_dispense_change(self):
        """Return True if this payment mode can dispense physical change."""
        return self.type == self.TYPE_CASH


class PaymentGLMapping(BaseModel):
    """Maps a ModeOfPayment to a General Ledger account name."""

    mode_of_payment = models.OneToOneField(
        ModeOfPayment,
        on_delete=models.PROTECT,
        related_name="gl_mapping",
    )
    default_account = models.CharField(max_length=200)

    class Meta:
        ordering = ["mode_of_payment__name"]

    def __str__(self):
        return f"{self.mode_of_payment.name} → {self.default_account}"

    def clean(self):
        super().clean()
        if self.mode_of_payment_id and not self.default_account:
            raise ValidationError({"default_account": "A default GL account name is required for the mapping."})

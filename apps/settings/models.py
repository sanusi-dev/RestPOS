from django.core.exceptions import ValidationError
from django.db import models

from apps.utils.models import BaseModel


class Restaurant(BaseModel):
    """The single settings record for this installation — identity, menu, stock, and POS behaviour."""

    company = models.CharField(max_length=200)
    invoice_series_prefix = models.CharField(max_length=20, default="REST-")
    address = models.TextField(blank=True)
    active_menu = models.ForeignKey(
        "menu.Menu",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_for_restaurants",
    )
    default_warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_restaurants",
    )

    class Meta:
        ordering = ["company"]

    def __str__(self):
        return self.company


    @classmethod
    def load(cls):
        """Return the singleton settings record with menu, menu items, and warehouse prefetched, or None."""
        return (
            cls.objects
            .select_related("active_menu", "default_warehouse")
            .prefetch_related("active_menu__items__item__item_group")
            .order_by("pk")
            .first()
        )

    def clean(self):
        super().clean()
        if not self.pk and Restaurant.objects.exists():
            raise ValidationError("Restaurant settings already exist — edit the existing record.")


class ProductionUnit(BaseModel):
    """A station that produces items — kitchen or bar — with printer routing."""

    FOOD = "FOOD"
    DRINKS = "DRINKS"
    DEPARTMENT_CHOICES = [(FOOD, "Food"), (DRINKS, "Drinks")]

    WIDTH_58MM = "WIDTH_58MM"
    WIDTH_80MM = "WIDTH_80MM"
    PAPER_WIDTH_CHOICES = [
        (WIDTH_58MM, "58mm"),
        (WIDTH_80MM, "80mm"),
    ]

    FULL_CUT = "FULL_CUT"
    PARTIAL_CUT = "PARTIAL_CUT"
    NO_CUT = "NO_CUT"
    CUT_MODE_CHOICES = [
        (FULL_CUT, "Full Cut"),
        (PARTIAL_CUT, "Partial Cut"),
        (NO_CUT, "No Cut"),
    ]

    name = models.CharField(max_length=100, unique=True)
    warehouse = models.ForeignKey("inventory.Warehouse", on_delete=models.PROTECT, related_name="production_units")
    department = models.CharField(max_length=10, choices=DEPARTMENT_CHOICES)
    block_takeaway_kot = models.BooleanField(default=False)
    printer_ip = models.CharField(max_length=50, blank=True)
    printer_paper_width = models.CharField(max_length=10, choices=PAPER_WIDTH_CHOICES, default=WIDTH_80MM)
    printer_cut_mode = models.CharField(max_length=15, choices=CUT_MODE_CHOICES, default=FULL_CUT)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

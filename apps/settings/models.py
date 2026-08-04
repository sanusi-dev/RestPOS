from django.core.exceptions import ValidationError
from django.db import models

from apps.utils.models import BaseModel


class Restaurant(BaseModel):
    """The single settings record for this installation — identity, menu, stock, and POS behaviour."""

    company = models.CharField(max_length=200)
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
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
        verbose_name="Bar / POS sales warehouse",
        help_text="Warehouse used for Bar stock and POS drink deductions.",
    )
    store_warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="store_for_restaurants",
        verbose_name="Central Store warehouse",
        help_text="Central Store used for all receipts and as the source of material transfers.",
    )
    max_open_drafts = models.PositiveIntegerField(
        default=50,
        help_text="Maximum normal POS drafts allowed on one active shift.",
    )

    class Meta:
        ordering = ["company"]

    def __str__(self):
        return self.company

    @classmethod
    def load(cls):
        """Return the singleton settings record with menu, menu items, and warehouse prefetched, or None."""
        return (
            cls.objects.select_related("active_menu", "default_warehouse", "store_warehouse")
            .prefetch_related("active_menu__items__item__item_group")
            .order_by("pk")
            .first()
        )

    def clean(self):
        super().clean()
        if not self.pk and Restaurant.objects.exists():
            raise ValidationError("Restaurant settings already exist — edit the existing record.")
        if self.max_open_drafts < 1:
            raise ValidationError({"max_open_drafts": "The open-draft limit must be at least 1."})
        if self.default_warehouse_id and self.default_warehouse.disabled:
            raise ValidationError({"default_warehouse": "The Bar / POS sales warehouse must be enabled."})
        if self.store_warehouse_id and self.store_warehouse.disabled:
            raise ValidationError({"store_warehouse": "The central Store warehouse must be enabled."})
        if self.store_warehouse_id and self.store_warehouse_id == self.default_warehouse_id:
            raise ValidationError({"store_warehouse": "The central Store must differ from the Bar / POS warehouse."})

        if self.pk:
            previous = Restaurant.objects.only("default_warehouse_id", "store_warehouse_id").get(pk=self.pk)
            if previous.default_warehouse_id != self.default_warehouse_id:
                from apps.orders.models import DRAFT, Order

                if Order.objects.filter(
                    status=DRAFT,
                    is_return=False,
                    stock_warehouse__isnull=False,
                ).exists():
                    raise ValidationError(
                        {"default_warehouse": "Clear or cancel open POS orders with drink reservations first."}
                    )
            if previous.store_warehouse_id != self.store_warehouse_id:
                from apps.inventory.models import PurchaseReceipt, StockEntry

                if (
                    StockEntry.objects.filter(status="DRAFT").exists()
                    or PurchaseReceipt.objects.filter(status="DRAFT").exists()
                ):
                    raise ValidationError(
                        {"store_warehouse": "Submit or remove draft stock documents before changing the central Store."}
                    )

        units = ProductionUnit.objects.select_related("warehouse").all()
        drinks_unit = next((unit for unit in units if unit.department == ProductionUnit.DRINKS), None)
        food_unit = next((unit for unit in units if unit.department == ProductionUnit.FOOD), None)
        if self.default_warehouse_id and drinks_unit and drinks_unit.warehouse_id != self.default_warehouse_id:
            raise ValidationError(
                {"default_warehouse": "The Bar / POS warehouse must match the Drinks production unit warehouse."}
            )
        if food_unit:
            if self.store_warehouse_id and food_unit.warehouse_id == self.store_warehouse_id:
                raise ValidationError({"store_warehouse": "The central Store must differ from the Kitchen warehouse."})
            if self.default_warehouse_id and food_unit.warehouse_id == self.default_warehouse_id:
                raise ValidationError({"default_warehouse": "The Bar / POS warehouse must differ from the Kitchen."})


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
        constraints = [
            models.UniqueConstraint(fields=["department"], name="settings_one_production_unit_per_department"),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.warehouse_id and self.warehouse.disabled:
            raise ValidationError({"warehouse": "The production unit warehouse must be enabled."})

        restaurant = Restaurant.load()
        if not restaurant or not self.warehouse_id:
            return
        if (
            self.department == self.DRINKS
            and restaurant.default_warehouse_id
            and self.warehouse_id != restaurant.default_warehouse_id
        ):
            raise ValidationError({"warehouse": "Drinks must use the configured Bar / POS sales warehouse."})
        if self.department == self.FOOD:
            if restaurant.store_warehouse_id and self.warehouse_id == restaurant.store_warehouse_id:
                raise ValidationError({"warehouse": "The Kitchen warehouse must differ from the central Store."})
            if restaurant.default_warehouse_id and self.warehouse_id == restaurant.default_warehouse_id:
                raise ValidationError({"warehouse": "The Kitchen warehouse must differ from the Bar / POS warehouse."})

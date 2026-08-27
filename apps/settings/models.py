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
    pos_allow_full_history = models.BooleanField(
        default=False,
        help_text="When enabled, cashiers can use All/Returns/Cancelled history filters. Managers always can.",
    )

    # Accounting (Phase 6) — settlement enforces the accounts it needs.
    default_income_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Default income account",
        help_text="Fallback income account for orders (item group and production unit accounts take precedence).",
    )
    default_expense_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Default expense account",
        help_text="Fallback expense account for COGS when the item group has none.",
    )
    round_off_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Round-off account",
    )
    account_for_change_amount = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Account for change amount",
        help_text="The cash account whose settle-time payment rows are reduced by the change given.",
    )
    write_off_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Write-off account",
    )
    wastage_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Wastage account",
        help_text="Expense account for non-restockable returned drinks.",
    )
    cash_shortage_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Cash shortage account",
    )
    cash_over_short_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Cash over/short account",
    )
    variance_approval_threshold = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Variance approval threshold",
        help_text="Absolute cash variance that requires a manager note to close. Blank = no approval gate.",
    )

    # Payables (Phase 2 §4.1) — supplier invoice/payment posting enforces these.
    default_payable_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Default payable account",
        help_text="Accounts-payable account credited by supplier invoices and debited by supplier payments.",
    )
    default_stock_in_hand_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Default stock-in-hand account",
        help_text="Stock account debited by supplier invoice stock lines when the item group has no expense account.",
    )

    # Inventory costing (PWAC D4/D5) — GRN accrual and cancellation drift.
    stock_received_but_not_billed_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Stock received but not billed (GRNI)",
        help_text="Liability account credited by goods receipts and debited by linked supplier invoices.",
    )
    inventory_price_variance_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Inventory price variance account",
        help_text=(
            "Expense account for cancellation WAC drift "
            "(receipt cancellations only; sale-return variance posts to COGS)."
        ),
    )

    class Meta:
        ordering = ["company"]

    def __str__(self):
        return self.company

    @classmethod
    def load(cls):
        """Return the singleton settings record with its direct relations loaded, or None."""
        return cls.objects.select_related("active_menu", "default_warehouse", "store_warehouse").order_by("pk").first()

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

        # Warehouse changes affect reservations and document posting; do not
        # let existing drafts silently move to a different stock location.
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

        # Store receives stock, Kitchen consumes FOOD, and Bar/POS supplies
        # DRINKS; these roles must continue pointing at compatible warehouses.
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
    income_account = models.ForeignKey(
        "accounting.LedgerAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Income account",
        help_text="Departmental income hook — Kitchen = FOOD income, Bar = DRINKS income.",
    )

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

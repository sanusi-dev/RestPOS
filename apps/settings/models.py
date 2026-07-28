from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import models

from apps.users.models import CustomUser
from apps.utils.models import BaseModel


class Branch(BaseModel):
    """A restaurant branch or physical location."""

    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

    @classmethod
    def get_default(cls):
        """Return the first branch (single-site default)."""
        return cls.objects.order_by("pk").first()


class Room(BaseModel):
    """A dining room or area within a branch."""

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="rooms")
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = [("branch", "name")]
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.branch_id:
            default_branch = Branch.get_default()
            if default_branch is None:
                raise ValidationError({"branch": "Create a branch in Settings before creating a room."})
            self.branch = default_branch
        super().save(*args, **kwargs)


class Table(BaseModel):
    """A physical table within a room. Branch is denormalized from room."""

    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="tables")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="tables")
    name = models.CharField(max_length=50)
    no_of_seats = models.IntegerField(null=True, blank=True)
    minimum_seating = models.IntegerField(null=True, blank=True)
    table_shape = models.CharField(
        max_length=20,
        choices=[("RECTANGLE", "Rectangle"), ("SQUARE", "Square"), ("CIRCLE", "Circle")],
        blank=True,
    )
    is_take_away = models.BooleanField(default=False)
    occupied = models.BooleanField(default=False, editable=False)
    latest_invoice_time = models.DateTimeField(null=True, blank=True, editable=False)
    layout_x = models.FloatField(null=True, blank=True)
    layout_y = models.FloatField(null=True, blank=True)
    layout_width = models.FloatField(null=True, blank=True)
    layout_height = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = [("room", "name")]
        ordering = ["room__name", "name"]

    def __str__(self):
        return self.name

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track room_id at load time so save() can skip the Room→Branch fetch
        # pair when room hasn't changed (layout edits, name edits, etc.).
        self._original_room_id = self.room_id

    def save(self, *args, **kwargs):
        if self.room_id and (self._state.adding or self._original_room_id != self.room_id):
            self.branch = self.room.branch
        super().save(*args, **kwargs)
        self._original_room_id = self.room_id


class Restaurant(BaseModel):
    """Restaurant-level configuration for a branch."""

    company = models.CharField(max_length=200)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="restaurants")
    invoice_series_prefix = models.CharField(max_length=20, default="REST-")
    address = models.TextField(blank=True)
    default_room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="restaurants")
    active_menu = models.ForeignKey(
        "menu.Menu",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_for_restaurants",
    )
    default_tax_template = models.ForeignKey(
        "TaxTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="restaurants",
    )

    class Meta:
        ordering = ["company"]

    def __str__(self):
        return self.company or self.branch.name

    def save(self, *args, **kwargs):
        if not self.branch_id:
            default_branch = Branch.get_default()
            if default_branch is None:
                raise ValidationError({"branch": "Create a branch in Settings before creating restaurant config."})
            self.branch = default_branch
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.branch_id:
            default_branch = Branch.get_default()
            if default_branch is not None:
                self.branch = default_branch
        if self.branch_id:
            if self.pk:
                existing = Restaurant.objects.filter(branch=self.branch).exclude(pk=self.pk)
            else:
                existing = Restaurant.objects.filter(branch=self.branch)
            if existing.exists():
                raise ValidationError({"branch": "A restaurant configuration already exists for this branch."})
        if self.default_room_id and self.branch_id and self.default_room.branch_id != self.branch_id:
            raise ValidationError({"default_room": "The default room must belong to the same branch."})


class UserRoomAssignment(BaseModel):
    """Assigns a user to a room. Branch is derived from room on save."""

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="room_assignments")
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="user_assignments")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="user_room_assignments")

    class Meta:
        unique_together = [("user", "room")]
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user.username} → {self.room.name}"

    def save(self, *args, **kwargs):
        if self.room_id:
            self.branch = self.room.branch
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.room_id:
            self.branch = self.room.branch


# ---------------------------------------------------------------------------
# Phase 6 — Tax Template
# ---------------------------------------------------------------------------


class TaxTemplate(BaseModel):
    """A named tax template with one or more tax rate lines."""

    title = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)
    disabled = models.BooleanField(default=False)
    company = models.CharField(max_length=200)
    tax_category = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["title"]
        unique_together = [("title", "company")]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if not self.company:
            restaurant = Restaurant.objects.first()
            if restaurant:
                self.company = restaurant.company
        if self.is_default and self.disabled:
            raise ValidationError("Disabled template must not be default.")
        if self.is_default and self.pk:
            TaxTemplate.objects.filter(company=self.company, is_default=True).exclude(pk=self.pk).update(
                is_default=False
            )
        if self.tax_category:
            existing = TaxTemplate.objects.filter(
                company=self.company, tax_category=self.tax_category, disabled=False
            ).exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError(
                    {"tax_category": f"A template with tax category '{self.tax_category}' already exists."}
                )


class TaxRate(BaseModel):
    """One tax line within a TaxTemplate."""

    ACTUAL = "ACTUAL"
    ON_NET_TOTAL = "ON_NET_TOTAL"
    ON_PREVIOUS_ROW_AMOUNT = "ON_PREVIOUS_ROW_AMOUNT"
    ON_PREVIOUS_ROW_TOTAL = "ON_PREVIOUS_ROW_TOTAL"
    ON_ITEM_QUANTITY = "ON_ITEM_QUANTITY"
    CHARGE_TYPE_CHOICES = [
        (ACTUAL, "Actual"),
        (ON_NET_TOTAL, "On Net Total"),
        (ON_PREVIOUS_ROW_AMOUNT, "On Previous Row Amount"),
        (ON_PREVIOUS_ROW_TOTAL, "On Previous Row Total"),
        (ON_ITEM_QUANTITY, "On Item Quantity"),
    ]

    tax_template = models.ForeignKey(TaxTemplate, on_delete=models.CASCADE, related_name="rates")
    charge_type = models.CharField(max_length=30, choices=CHARGE_TYPE_CHOICES, default=ON_NET_TOTAL)
    rate = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0"))
    account_head = models.CharField(max_length=200)
    description = models.CharField(max_length=255)
    cost_center = models.CharField(max_length=200, blank=True)
    included_in_print_rate = models.BooleanField(default=False)
    row_id = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.get_charge_type_display()} {self.rate}% → {self.account_head}"


# ---------------------------------------------------------------------------
# Phase 6 — POS Profile
# ---------------------------------------------------------------------------


class POSProfile(BaseModel):
    """Master configuration for a POS terminal or cashier role."""

    ALWAYS_ASK = "ALWAYS_ASK"
    SAVE_AND_LOAD_NEW = "SAVE_AND_LOAD_NEW"
    DISCARD_AND_LOAD_NEW = "DISCARD_AND_LOAD_NEW"
    ACTION_CHOICES = [
        (ALWAYS_ASK, "Always Ask"),
        (SAVE_AND_LOAD_NEW, "Save Changes and Load New"),
        (DISCARD_AND_LOAD_NEW, "Discard Changes and Load New"),
    ]
    GRAND_TOTAL = "GRAND_TOTAL"
    NET_TOTAL = "NET_TOTAL"
    DISCOUNT_ON_CHOICES = [(GRAND_TOTAL, "Grand Total"), (NET_TOTAL, "Net Total")]

    name = models.CharField(max_length=100)
    company = models.CharField(max_length=200)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="pos_profiles")
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pos_profiles",
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        related_name="pos_profiles",
    )
    disabled = models.BooleanField(default=False)
    currency = models.CharField(max_length=3, default="NGN")
    selling_price_list = models.ForeignKey(
        "menu.PriceList",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pos_profiles",
    )
    cost_center = models.CharField(max_length=200, blank=True)
    income_account = models.CharField(max_length=200, blank=True)
    expense_account = models.CharField(max_length=200, blank=True)
    write_off_account = models.CharField(max_length=200, blank=True)
    write_off_cost_center = models.CharField(max_length=200, blank=True)
    write_off_limit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1.00"))
    account_for_change_amount = models.CharField(max_length=200, blank=True)
    set_grand_total_to_default_mop = models.BooleanField(default=True)
    allow_partial_payment = models.BooleanField(default=False)
    apply_discount_on = models.CharField(max_length=15, choices=DISCOUNT_ON_CHOICES, default=GRAND_TOTAL)
    enable_discount = models.BooleanField(default=False)
    action_on_new_invoice = models.CharField(max_length=40, choices=ACTION_CHOICES, default=ALWAYS_ASK)
    validate_stock_on_save = models.BooleanField(default=False)
    hide_images = models.BooleanField(default=False)
    hide_unavailable_items = models.BooleanField(default=False)
    auto_add_item_to_cart = models.BooleanField(default=False)
    allow_rate_change = models.BooleanField(default=False)
    allow_discount_change = models.BooleanField(default=False)
    allow_warehouse_change = models.BooleanField(default=False)
    print_receipt_on_order_complete = models.BooleanField(default=False)
    view_all_status = models.BooleanField(default=False)
    paid_limit = models.IntegerField(default=20)
    edit_order_type = models.BooleanField(default=False)
    remove_items = models.BooleanField(default=False)
    show_image = models.BooleanField(default=True)
    require_daily_pos_close = models.BooleanField(default=False)
    table_attention_time = models.IntegerField(default=0)
    multiple_cashier = models.BooleanField(default=False)
    kot_naming_series = models.CharField(max_length=50, default="KOT-####")
    reset_order_number_daily = models.BooleanField(default=False)
    kot_warning_time = models.IntegerField(default=15)
    notify_kot_delay = models.BooleanField(default=False)
    enable_kot_reprint = models.BooleanField(default=False)
    reprint_kot_format = models.CharField(max_length=100, blank=True)
    print_format = models.CharField(max_length=100, blank=True)
    applicable_users = models.ManyToManyField(
        CustomUser, through="POSProfileUser", related_name="pos_profiles", blank=True
    )
    payments = models.ManyToManyField(
        "payments.ModeOfPayment",
        through="POSProfilePayment",
        related_name="pos_profiles",
        blank=True,
    )
    item_groups = models.ManyToManyField("inventory.ItemGroup", related_name="pos_profiles", blank=True)
    role_allowed_for_billing = models.ManyToManyField(Group, related_name="billing_profiles", blank=True)
    role_restricted_for_table_order = models.ManyToManyField(
        Group, related_name="table_order_restricted_profiles", blank=True
    )
    transfer_role_permissions = models.ManyToManyField(Group, related_name="transfer_profiles", blank=True)
    notification_recipients = models.ManyToManyField(Group, related_name="delay_notification_profiles", blank=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("name", "branch")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.branch_id:
            default_branch = Branch.get_default()
            if default_branch is None:
                raise ValidationError({"branch": "Create a branch in Settings before creating a POS profile."})
            self.branch = default_branch
        if not self.restaurant_id and self.branch_id:
            self.restaurant = self.branch.restaurants.first()
        if not self.company and self.restaurant_id:
            self.company = self.restaurant.company
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.company and self.branch_id:
            restaurant = self.branch.restaurants.first()
            if restaurant:
                self.company = restaurant.company
        if self.disabled and self.pk:
            from apps.staff.models import POSOpeningEntry

            open_exists = POSOpeningEntry.objects.filter(
                pos_profile=self, status="SUBMITTED", closing_entry__isnull=True
            ).exists()
            if open_exists:
                raise ValidationError("POS Profile cannot be disabled as there are ongoing POS sessions.")
        if self.pk and not self.payment_links.exists():
            raise ValidationError("Payment methods are mandatory. Please add at least one payment method.")
        if self.pk:
            defaults = self.payment_links.filter(is_default=True)
            if defaults.count() != 1:
                raise ValidationError("Please select exactly one default mode of payment.")
            from apps.payments.models import PaymentGLMapping

            modes_without_gl = []
            for link in self.payment_links.select_related("mode_of_payment"):
                if not PaymentGLMapping.objects.filter(
                    mode_of_payment=link.mode_of_payment, company=self.company
                ).exists():
                    modes_without_gl.append(link.mode_of_payment.name)
            if modes_without_gl:
                raise ValidationError(
                    f"Please set default account for mode(s) of payment: {', '.join(modes_without_gl)}"
                )
            seen = set()
            for ig in self.item_groups.all():
                if ig.pk in seen:
                    raise ValidationError("Duplicate item group found.")
                seen.add(ig.pk)
            for link in self.user_links.select_related("user").filter(is_default=True):
                other = (
                    POSProfileUser.objects.filter(
                        user=link.user,
                        is_default=True,
                        pos_profile__company=self.company,
                        pos_profile__disabled=False,
                    )
                    .exclude(pos_profile=self)
                    .exists()
                )
                if other:
                    raise ValidationError(
                        f"User {link.user.username} already has a default POS Profile in {self.company}."
                    )


class POSProfileUser(BaseModel):
    """Through model linking POSProfile to CustomUser with per-user flags."""

    pos_profile = models.ForeignKey(POSProfile, on_delete=models.CASCADE, related_name="user_links")
    user = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name="profile_links")
    is_default = models.BooleanField(default=False)
    is_main_cashier = models.BooleanField(default=False)

    class Meta:
        unique_together = [("pos_profile", "user")]
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user.username} @ {self.pos_profile.name}"


class POSProfilePayment(BaseModel):
    """Through model linking POSProfile to ModeOfPayment with per-mode flags."""

    pos_profile = models.ForeignKey(POSProfile, on_delete=models.CASCADE, related_name="payment_links")
    mode_of_payment = models.ForeignKey(
        "payments.ModeOfPayment",
        on_delete=models.PROTECT,
        related_name="profile_links",
    )
    is_default = models.BooleanField(default=False)
    allow_in_returns = models.BooleanField(default=False)

    class Meta:
        unique_together = [("pos_profile", "mode_of_payment")]
        ordering = ["mode_of_payment__name"]

    def __str__(self):
        return f"{self.mode_of_payment.name} @ {self.pos_profile.name}"


# ---------------------------------------------------------------------------
# Phase 6 — Production Unit
# ---------------------------------------------------------------------------


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

    name = models.CharField(max_length=100)
    pos_profile = models.ForeignKey(
        POSProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="production_units",
    )
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="production_units")
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        related_name="production_units",
    )
    department = models.CharField(max_length=10, choices=DEPARTMENT_CHOICES)
    block_takeaway_kot = models.BooleanField(default=False)
    printer_ip = models.CharField(max_length=50, blank=True)
    printer_paper_width = models.CharField(max_length=10, choices=PAPER_WIDTH_CHOICES, default=WIDTH_80MM)
    printer_cut_mode = models.CharField(max_length=15, choices=CUT_MODE_CHOICES, default=FULL_CUT)

    class Meta:
        ordering = ["name"]
        unique_together = [("name", "branch")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.branch_id:
            if self.pos_profile_id and self.pos_profile.branch_id:
                self.branch = self.pos_profile.branch
            else:
                default_branch = Branch.get_default()
                if default_branch is None:
                    raise ValidationError({"branch": "Create a branch in Settings before creating a production unit."})
                self.branch = default_branch
        if not self.warehouse_id and self.pos_profile_id and self.pos_profile.warehouse_id:
            self.warehouse = self.pos_profile.warehouse
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.branch_id:
            if self.pos_profile_id and self.pos_profile.branch_id:
                self.branch = self.pos_profile.branch
            else:
                default_branch = Branch.get_default()
                if default_branch is not None:
                    self.branch = default_branch
        if not self.warehouse_id and self.pos_profile_id and self.pos_profile.warehouse_id:
            self.warehouse = self.pos_profile.warehouse
        if self.pos_profile_id and self.branch_id and self.pos_profile.branch_id != self.branch_id:
            raise ValidationError({"branch": "Branch must match the linked POS profile's branch."})

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

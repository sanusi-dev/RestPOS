from django.contrib import admin

from .models import (
    Branch,
    POSProfile,
    POSProfilePayment,
    POSProfileUser,
    ProductionUnit,
    Restaurant,
    Room,
    Table,
    TaxRate,
    TaxTemplate,
    UserRoomAssignment,
)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "created_at")
    list_filter = ("branch",)
    list_select_related = ("branch",)
    search_fields = ("name", "branch__name")
    ordering = ("branch__name", "name")


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("name", "room", "branch", "no_of_seats", "table_shape", "is_take_away", "occupied")
    list_filter = ("branch", "room", "table_shape", "is_take_away", "occupied")
    list_select_related = ("room", "branch")
    search_fields = ("name", "room__name", "branch__name")
    readonly_fields = ("occupied", "latest_invoice_time")
    ordering = ("room__name", "name")


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ("company", "branch", "invoice_series_prefix", "default_room")
    list_filter = ("branch",)
    list_select_related = ("branch", "default_room")
    search_fields = ("company", "branch__name")
    ordering = ("branch__name",)


@admin.register(UserRoomAssignment)
class UserRoomAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "room", "branch", "created_at")
    list_filter = ("branch", "room")
    list_select_related = ("user", "room", "branch")
    search_fields = ("user__username", "user__email", "room__name")
    ordering = ("user__username",)


@admin.register(TaxTemplate)
class TaxTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "is_default", "disabled")
    list_filter = ("is_default", "disabled")
    search_fields = ("title",)
    ordering = ("title",)


@admin.register(TaxRate)
class TaxRateAdmin(admin.ModelAdmin):
    list_display = ("tax_template", "charge_type", "rate", "account_head")
    list_filter = ("charge_type",)
    list_select_related = ("tax_template",)
    search_fields = ("account_head", "description")
    ordering = ("pk",)


@admin.register(POSProfile)
class POSProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "warehouse", "disabled")
    list_filter = ("disabled", "branch")
    list_select_related = ("branch", "warehouse")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(POSProfileUser)
class POSProfileUserAdmin(admin.ModelAdmin):
    list_display = ("pos_profile", "user", "is_default", "is_main_cashier")
    list_filter = ("is_default", "is_main_cashier")
    list_select_related = ("pos_profile", "user")
    search_fields = ("user__username", "pos_profile__name")
    ordering = ("user__username",)


@admin.register(POSProfilePayment)
class POSProfilePaymentAdmin(admin.ModelAdmin):
    list_display = ("pos_profile", "mode_of_payment", "is_default", "allow_in_returns")
    list_filter = ("is_default",)
    list_select_related = ("pos_profile", "mode_of_payment")
    search_fields = ("pos_profile__name", "mode_of_payment__name")
    ordering = ("mode_of_payment__name",)


@admin.register(ProductionUnit)
class ProductionUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "department", "pos_profile", "printer_ip")
    list_filter = ("department", "branch")
    list_select_related = ("branch", "pos_profile")
    search_fields = ("name",)
    ordering = ("name",)

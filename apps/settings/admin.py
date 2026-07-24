from django.contrib import admin

from .models import Branch, Restaurant, Room, Table, UserRoomAssignment


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

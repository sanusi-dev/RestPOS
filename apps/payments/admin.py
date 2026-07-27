from django.contrib import admin

from .models import ModeOfPayment, PaymentGLMapping


@admin.register(ModeOfPayment)
class ModeOfPaymentAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "enabled", "created_at")
    list_filter = ("type", "enabled")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(PaymentGLMapping)
class PaymentGLMappingAdmin(admin.ModelAdmin):
    list_display = ("mode_of_payment", "company", "default_account", "created_at")
    list_filter = ("company",)
    list_select_related = ("mode_of_payment",)
    search_fields = ("mode_of_payment__name", "default_account")
    ordering = ("mode_of_payment__name", "company")

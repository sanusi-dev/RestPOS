from django.contrib import admin

from .models import (
    DailyPnL,
    DailyPnLAdHoc,
    DailyPnLCogsRow,
    DailyPnLConsumptionRow,
    DailyPnLLine,
    DailyPnLMaterialQty,
    DailyPnLTheoreticalRow,
    DailyPnLUnmappedRow,
    PnLConfiguration,
    PnLMaterial,
    PnLRecurringExpense,
)


@admin.register(PnLConfiguration)
class PnLConfigurationAdmin(admin.ModelAdmin):
    list_display = ("business_day_start_hour", "electricity_rate", "daily_depreciation", "include_cash_variance")


@admin.register(PnLMaterial)
class PnLMaterialAdmin(admin.ModelAdmin):
    list_display = ("name", "unit", "rate", "disabled")
    list_filter = ("disabled",)


@admin.register(PnLRecurringExpense)
class PnLRecurringExpenseAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "amount", "percent", "department", "disabled")
    list_filter = ("kind", "disabled")


class DailyPnLLineInline(admin.TabularInline):
    model = DailyPnLLine
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in DailyPnLLine._meta.fields if f.name != "id"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DailyPnL)
class DailyPnLAdmin(admin.ModelAdmin):
    list_display = ("business_date", "status", "gross_sales", "gross_profit", "net_profit")
    list_filter = ("status",)
    inlines = [DailyPnLLineInline]
    readonly_fields = ("period_start", "period_end", "submitted_at", "submitted_by")


admin.site.register(DailyPnLMaterialQty)
admin.site.register(DailyPnLAdHoc)
admin.site.register(DailyPnLCogsRow)
admin.site.register(DailyPnLConsumptionRow)
admin.site.register(DailyPnLTheoreticalRow)
admin.site.register(DailyPnLUnmappedRow)

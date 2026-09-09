from django.contrib import admin

from apps.utils.admin import dev_admin_bypass

from .models import (
    FiscalYear,
    GLEntry,
    JournalEntry,
    JournalEntryAccount,
    LedgerAccount,
    Supplier,
    SupplierInvoice,
    SupplierInvoiceExpense,
    SupplierInvoiceItem,
    SupplierPayment,
    SupplierPaymentAllocation,
)


@admin.register(LedgerAccount)
class LedgerAccountAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "is_group", "account_type", "disabled", "freeze_account")
    list_filter = ("account_type", "is_group", "disabled", "freeze_account")
    list_select_related = ("parent",)
    search_fields = ("name", "account_number")
    ordering = ("name",)


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ("name", "year_start_date", "year_end_date", "is_short_year", "disabled")
    list_filter = ("disabled", "is_short_year")
    search_fields = ("name",)
    ordering = ("-year_start_date",)


@admin.register(GLEntry)
class GLEntryAdmin(admin.ModelAdmin):
    list_display = (
        "posting_date",
        "account",
        "debit",
        "credit",
        "voucher_type",
        "voucher_no",
        "fiscal_year",
        "is_cancelled",
        "is_opening",
    )
    list_filter = ("voucher_type", "is_cancelled", "is_opening", "fiscal_year")
    list_select_related = ("account", "fiscal_year")
    search_fields = ("voucher_no", "account__name")
    date_hierarchy = "posting_date"
    ordering = ("-posting_date", "-pk")

    def get_readonly_fields(self, request, obj=None):
        if dev_admin_bypass(request):
            return super().get_readonly_fields(request, obj)
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return bool(dev_admin_bypass(request))

    def has_change_permission(self, request, obj=None):
        return bool(dev_admin_bypass(request))

    def has_delete_permission(self, request, obj=None):
        return bool(dev_admin_bypass(request))


class JournalEntryAccountInline(admin.TabularInline):
    model = JournalEntryAccount
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return bool(dev_admin_bypass(request))


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "voucher_type",
        "posting_date",
        "status",
        "total_debit",
        "total_credit",
        "is_opening",
        "amended_from",
    )
    list_filter = ("voucher_type", "status", "is_opening")
    list_select_related = ("amended_from",)
    search_fields = ("reference_no", "remark")
    date_hierarchy = "posting_date"
    ordering = ("-posting_date", "-pk")
    readonly_fields = (
        "total_debit",
        "total_credit",
        "difference",
        "is_opening",
        "amended_from",
    )
    inlines = (JournalEntryAccountInline,)

    def get_readonly_fields(self, request, obj=None):
        if dev_admin_bypass(request):
            return []
        return super().get_readonly_fields(request, obj)

    def has_delete_permission(self, request, obj=None):
        return bool(dev_admin_bypass(request))


@admin.register(JournalEntryAccount)
class JournalEntryAccountAdmin(admin.ModelAdmin):
    list_display = ("journal_entry", "account", "debit", "credit")
    list_select_related = ("journal_entry", "account")
    search_fields = ("account__name", "journal_entry__reference_no")
    ordering = ("-journal_entry__posting_date", "-pk")

    def get_readonly_fields(self, request, obj=None):
        if dev_admin_bypass(request):
            return super().get_readonly_fields(request, obj)
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return bool(dev_admin_bypass(request))

    def has_change_permission(self, request, obj=None):
        return bool(dev_admin_bypass(request))

    def has_delete_permission(self, request, obj=None):
        return bool(dev_admin_bypass(request))


class SupplierInvoiceItemInline(admin.TabularInline):
    model = SupplierInvoiceItem
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return bool(dev_admin_bypass(request))


class SupplierInvoiceExpenseInline(admin.TabularInline):
    model = SupplierInvoiceExpense
    extra = 0


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = (
        "supplier_name",
        "supplier_type",
        "contact_person",
        "phone",
        "payable_account",
        "is_default",
        "disabled",
    )
    list_filter = ("supplier_type", "is_default", "disabled")
    list_select_related = ("payable_account",)
    search_fields = ("supplier_name", "contact_person", "phone", "email", "tax_id")
    ordering = ("supplier_name",)


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "supplier",
        "posting_date",
        "due_date",
        "status",
        "total",
        "outstanding_amount",
        "bill_no",
    )
    list_filter = ("status", "posting_date")
    list_select_related = ("supplier", "purchase_receipt")
    search_fields = ("invoice_number", "supplier__supplier_name", "bill_no")
    date_hierarchy = "posting_date"
    ordering = ("-posting_date", "-pk")
    inlines = (SupplierInvoiceItemInline, SupplierInvoiceExpenseInline)

    def get_readonly_fields(self, request, obj=None):
        if dev_admin_bypass(request):
            return super().get_readonly_fields(request, obj)
        return ["invoice_number", "total", "outstanding_amount"]

    def has_delete_permission(self, request, obj=None):
        return bool(dev_admin_bypass(request))


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ("payment_number", "supplier", "posting_date", "mode_of_payment", "paid_amount", "status")
    list_filter = ("status", "posting_date", "mode_of_payment")
    list_select_related = ("supplier", "mode_of_payment")
    search_fields = ("payment_number", "supplier__supplier_name", "reference_no")
    date_hierarchy = "posting_date"
    ordering = ("-posting_date", "-pk")

    def get_readonly_fields(self, request, obj=None):
        if dev_admin_bypass(request):
            return super().get_readonly_fields(request, obj)
        return ["payment_number"]

    def has_delete_permission(self, request, obj=None):
        return bool(dev_admin_bypass(request))


@admin.register(SupplierPaymentAllocation)
class SupplierPaymentAllocationAdmin(admin.ModelAdmin):
    list_display = ("payment", "invoice", "outstanding_amount", "allocated_amount")
    list_select_related = ("payment", "invoice")
    search_fields = ("payment__payment_number", "invoice__invoice_number")
    ordering = ("-payment__posting_date", "-pk")

    def get_readonly_fields(self, request, obj=None):
        if dev_admin_bypass(request):
            return super().get_readonly_fields(request, obj)
        return ["outstanding_amount"]

    def has_delete_permission(self, request, obj=None):
        return bool(dev_admin_bypass(request))


@admin.register(SupplierInvoiceExpense)
class SupplierInvoiceExpenseAdmin(admin.ModelAdmin):
    list_display = ("invoice", "description", "amount")
    list_select_related = ("invoice",)
    search_fields = ("invoice__invoice_number", "description")
    ordering = ("-invoice__posting_date", "-pk")

    def get_readonly_fields(self, request, obj=None):
        if dev_admin_bypass(request):
            return super().get_readonly_fields(request, obj)
        return ["invoice"]

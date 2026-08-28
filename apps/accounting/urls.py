"""URL configuration for the accounting app."""

from django.urls import path

from . import payables_views, views

app_name = "accounting"

urlpatterns = [
    path("", view=views.accounting_dashboard, name="dashboard"),
    # Chart of Accounts
    path("chart-of-accounts/", view=views.chart_of_accounts, name="chart_of_accounts"),
    path("chart-of-accounts/<int:pk>/children/", view=views.account_children, name="account_children"),
    path("chart-of-accounts/create/", view=views.account_create, name="account_create"),
    path("chart-of-accounts/<int:pk>/", view=views.account_detail, name="account_detail"),
    path("chart-of-accounts/<int:pk>/edit/", view=views.account_update, name="account_update"),
    # Journal Entries
    path("journal-entries/", view=views.journal_entry_list, name="journal_entry_list"),
    path("journal-entries/create/", view=views.journal_entry_create, name="journal_entry_create"),
    path("journal-entries/accounts/add/", view=views.journal_entry_account_add, name="journal_entry_account_add"),
    path(
        "journal-entries/accounts/remove/<int:index>/",
        view=views.journal_entry_account_remove,
        name="journal_entry_account_remove",
    ),
    path("journal-entries/<int:pk>/", view=views.journal_entry_detail, name="journal_entry_detail"),
    path("journal-entries/<int:pk>/review/", view=views.journal_entry_review, name="journal_entry_review"),
    path("journal-entries/<int:pk>/edit/", view=views.journal_entry_update, name="journal_entry_update"),
    path("journal-entries/<int:pk>/submit/", view=views.journal_entry_submit, name="journal_entry_submit"),
    path("journal-entries/<int:pk>/cancel/", view=views.journal_entry_cancel, name="journal_entry_cancel"),
    path("journal-entries/<int:pk>/amend/", view=views.journal_entry_amend, name="journal_entry_amend"),
    # GL Entries
    path("gl-entries/", view=views.gl_entry_list, name="gl_entry_list"),
    # Fiscal Years
    path("fiscal-years/", view=views.fiscal_year_list, name="fiscal_year_list"),
    path("fiscal-years/create/", view=views.fiscal_year_create, name="fiscal_year_create"),
    path("fiscal-years/<int:pk>/edit/", view=views.fiscal_year_update, name="fiscal_year_update"),
    # Supplier Payables (Phase 2 §4.1)
    path("suppliers/", view=payables_views.supplier_list, name="supplier_list"),
    path("suppliers/create/", view=payables_views.supplier_create, name="supplier_create"),
    path("suppliers/<int:pk>/", view=payables_views.supplier_detail, name="supplier_detail"),
    path("suppliers/<int:pk>/edit/", view=payables_views.supplier_update, name="supplier_update"),
    path("supplier-invoices/", view=payables_views.supplier_invoice_list, name="supplier_invoice_list"),
    path("supplier-invoices/create/", view=payables_views.supplier_invoice_create, name="supplier_invoice_create"),
    path(
        "supplier-invoices/expenses/add/",
        view=payables_views.supplier_invoice_expense_add,
        name="supplier_invoice_expense_add",
    ),
    path(
        "supplier-invoices/expenses/remove/<int:index>/",
        view=payables_views.supplier_invoice_expense_remove,
        name="supplier_invoice_expense_remove",
    ),
    path("supplier-invoices/<int:pk>/", view=payables_views.supplier_invoice_detail, name="supplier_invoice_detail"),
    path(
        "supplier-invoices/<int:pk>/edit/",
        view=payables_views.supplier_invoice_update,
        name="supplier_invoice_update",
    ),
    path(
        "supplier-invoices/<int:pk>/submit/",
        view=payables_views.supplier_invoice_submit,
        name="supplier_invoice_submit",
    ),
    path(
        "supplier-invoices/<int:pk>/cancel/",
        view=payables_views.supplier_invoice_cancel,
        name="supplier_invoice_cancel",
    ),
    path("supplier-payments/", view=payables_views.supplier_payment_list, name="supplier_payment_list"),
    path("supplier-payments/create/", view=payables_views.supplier_payment_create, name="supplier_payment_create"),
    path(
        "supplier-payments/allocations/add/",
        view=payables_views.supplier_payment_alloc_add,
        name="supplier_payment_alloc_add",
    ),
    path(
        "supplier-payments/allocations/remove/<int:index>/",
        view=payables_views.supplier_payment_alloc_remove,
        name="supplier_payment_alloc_remove",
    ),
    path("supplier-payments/<int:pk>/", view=payables_views.supplier_payment_detail, name="supplier_payment_detail"),
    path(
        "supplier-payments/<int:pk>/edit/",
        view=payables_views.supplier_payment_update,
        name="supplier_payment_update",
    ),
    path(
        "supplier-payments/<int:pk>/submit/",
        view=payables_views.supplier_payment_submit,
        name="supplier_payment_submit",
    ),
    path(
        "supplier-payments/<int:pk>/cancel/",
        view=payables_views.supplier_payment_cancel,
        name="supplier_payment_cancel",
    ),
]

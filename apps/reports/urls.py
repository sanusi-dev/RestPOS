"""URL configuration for the reports app."""

from django.urls import path

from . import report_views, views

app_name = "reports"

urlpatterns = [
    path("", view=views.daily_pnl_list, name="daily_pnl_list"),
    path("settings/", view=views.pnl_settings, name="pnl_settings"),
    path("sales/today/", view=report_views.sales_today, name="sales_today"),
    path("sales/daywise/", view=report_views.sales_daywise, name="sales_daywise"),
    path("sales/monthwise/", view=report_views.sales_monthwise, name="sales_monthwise"),
    path("sales/items/", view=report_views.sales_itemwise, name="sales_itemwise"),
    path("sales/employees/", view=report_views.sales_employeewise, name="sales_employeewise"),
    path("sales/service/", view=report_views.sales_servicewise, name="sales_servicewise"),
    path("sales/time/", view=report_views.sales_timewise, name="sales_timewise"),
    path("sales/cancelled/", view=report_views.sales_cancelled, name="sales_cancelled"),
    path("sales/average-bill/", view=report_views.sales_average_bill, name="sales_average_bill"),
    path("sales/register/", view=report_views.pos_register, name="pos_register"),
    path("accounting/gl/", view=report_views.gl_report, name="gl_report"),
    path("accounting/trial-balance/", view=report_views.trial_balance, name="trial_balance"),
    path("accounting/profit-and-loss/", view=report_views.simple_pnl, name="simple_pnl"),
    path("daily-pnl/create/", view=views.daily_pnl_create, name="daily_pnl_create"),
    path("daily-pnl/<int:pk>/", view=views.daily_pnl_detail, name="daily_pnl_detail"),
    path("daily-pnl/<int:pk>/edit/", view=views.daily_pnl_update, name="daily_pnl_update"),
    path("daily-pnl/<int:pk>/preview/", view=views.daily_pnl_preview, name="daily_pnl_preview"),
    path("daily-pnl/<int:pk>/submit/", view=views.daily_pnl_submit, name="daily_pnl_submit"),
    path("daily-pnl/<int:pk>/cancel/", view=views.daily_pnl_cancel, name="daily_pnl_cancel"),
    path("daily-pnl/<int:pk>/amend/", view=views.daily_pnl_amend, name="daily_pnl_amend"),
    path("daily-pnl/<int:pk>/materials/add/", view=views.daily_pnl_material_add, name="daily_pnl_material_add"),
    path(
        "daily-pnl/<int:pk>/materials/remove/<int:index>/",
        view=views.daily_pnl_material_remove,
        name="daily_pnl_material_remove",
    ),
    path("daily-pnl/<int:pk>/adhoc/add/", view=views.daily_pnl_adhoc_add, name="daily_pnl_adhoc_add"),
    path(
        "daily-pnl/<int:pk>/adhoc/remove/<int:index>/",
        view=views.daily_pnl_adhoc_remove,
        name="daily_pnl_adhoc_remove",
    ),
]

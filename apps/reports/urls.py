"""URL configuration for the reports app."""

from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", view=views.daily_pnl_list, name="daily_pnl_list"),
    path("settings/", view=views.pnl_settings, name="pnl_settings"),
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

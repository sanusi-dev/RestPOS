from django.urls import path

from . import views

app_name = "settings"

urlpatterns = [
    path("", view=views.settings_dashboard, name="dashboard"),
    path("restaurant/", view=views.restaurant_settings, name="restaurant_settings"),
    path("staff/", view=views.staff_list, name="staff_list"),
    path("staff/create/", view=views.staff_create, name="staff_create"),
    path("staff/<int:pk>/assign/<str:role>/", view=views.staff_assign_role, name="staff_assign_role"),
    path("staff/<int:pk>/remove/", view=views.staff_remove_role, name="staff_remove_role"),
    path("staff/<int:pk>/toggle-active/", view=views.staff_toggle_active, name="staff_toggle_active"),
    path("production-units/", view=views.production_unit_list, name="production_unit_list"),
    path("production-units/create/", view=views.production_unit_create, name="production_unit_create"),
    path("production-units/<int:pk>/", view=views.production_unit_detail, name="production_unit_detail"),
    path("production-units/<int:pk>/edit/", view=views.production_unit_update, name="production_unit_update"),
    path("production-units/<int:pk>/delete/", view=views.production_unit_delete, name="production_unit_delete"),
]

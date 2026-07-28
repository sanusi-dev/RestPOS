from django.urls import path

from . import views

app_name = "settings"

urlpatterns = [
    path("", view=views.settings_dashboard, name="dashboard"),
    path("branches/", view=views.branch_list, name="branch_list"),
    path("branches/create/", view=views.branch_create, name="branch_create"),
    path("branches/<int:pk>/", view=views.branch_detail, name="branch_detail"),
    path("branches/<int:pk>/edit/", view=views.branch_update, name="branch_update"),
    path("rooms/", view=views.room_list, name="room_list"),
    path("rooms/create/", view=views.room_create, name="room_create"),
    path("rooms/<int:pk>/", view=views.room_detail, name="room_detail"),
    path("rooms/<int:pk>/edit/", view=views.room_update, name="room_update"),
    path("tables/", view=views.table_list, name="table_list"),
    path("tables/layout/", view=views.table_layout, name="table_layout"),
    path("tables/create/", view=views.table_create, name="table_create"),
    path("tables/<int:pk>/", view=views.table_detail, name="table_detail"),
    path("tables/<int:pk>/edit/", view=views.table_update, name="table_update"),
    path("tables/<int:pk>/layout/", view=views.table_update_layout, name="table_update_layout"),
    path("restaurant/", view=views.restaurant_detail, name="restaurant_detail"),
    path("restaurant/edit/", view=views.restaurant_update, name="restaurant_update"),
    path("users/", view=views.user_room_list, name="user_room_list"),
    path("users/create/", view=views.user_room_create, name="user_room_create"),
    path("users/<int:pk>/edit/", view=views.user_room_update, name="user_room_update"),
    path("users/<int:pk>/delete/", view=views.user_room_delete, name="user_room_delete"),
    path("staff/", view=views.staff_list, name="staff_list"),
    path("staff/<int:pk>/assign/<str:role>/", view=views.staff_assign_role, name="staff_assign_role"),
    path("staff/<int:pk>/remove/", view=views.staff_remove_role, name="staff_remove_role"),
    # POS Profile (singleton)
    path("pos-profile/", view=views.pos_profile_settings, name="pos_profile_settings"),
    # Production Units
    path("production-units/", view=views.production_unit_list, name="production_unit_list"),
    path("production-units/create/", view=views.production_unit_create, name="production_unit_create"),
    path("production-units/<int:pk>/", view=views.production_unit_detail, name="production_unit_detail"),
    path("production-units/<int:pk>/edit/", view=views.production_unit_update, name="production_unit_update"),
    path("production-units/<int:pk>/delete/", view=views.production_unit_delete, name="production_unit_delete"),
    # Tax Templates
    path("tax-templates/", view=views.tax_template_list, name="tax_template_list"),
    path("tax-templates/create/", view=views.tax_template_create, name="tax_template_create"),
    path("tax-templates/<int:pk>/", view=views.tax_template_detail, name="tax_template_detail"),
    path("tax-templates/<int:pk>/edit/", view=views.tax_template_update, name="tax_template_update"),
    path("tax-templates/<int:pk>/delete/", view=views.tax_template_delete, name="tax_template_delete"),
]

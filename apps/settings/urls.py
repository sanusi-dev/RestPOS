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
]

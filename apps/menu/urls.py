from django.urls import path

from . import views

app_name = "menu"

urlpatterns = [
    path("", view=views.menu_dashboard, name="dashboard"),
    # Menu
    path("menus/", view=views.menu_list, name="menu_list"),
    path("menus/create/", view=views.menu_create, name="menu_create"),
    path("menus/<int:pk>/", view=views.menu_detail, name="menu_detail"),
    path("menus/<int:pk>/edit/", view=views.menu_update, name="menu_update"),
    # MenuItem
    path("menu-items/", view=views.menu_item_list, name="menu_item_list"),
    path("menu-items/create/", view=views.menu_item_create, name="menu_item_create"),
    path("menu-items/<int:pk>/edit/", view=views.menu_item_update, name="menu_item_update"),
    path("menu-items/<int:pk>/delete/", view=views.menu_item_delete, name="menu_item_delete"),
    # ItemAddOn
    path("add-ons/", view=views.add_on_list, name="add_on_list"),
    path("add-ons/create/", view=views.add_on_create, name="add_on_create"),
    path("add-ons/<int:pk>/edit/", view=views.add_on_update, name="add_on_update"),
    path("add-ons/<int:pk>/delete/", view=views.add_on_delete, name="add_on_delete"),
    # ItemVariant
    path("variants/", view=views.variant_list, name="variant_list"),
    path("variants/create/", view=views.variant_create, name="variant_create"),
    path("variants/<int:pk>/edit/", view=views.variant_update, name="variant_update"),
    path("variants/<int:pk>/delete/", view=views.variant_delete, name="variant_delete"),
    # PriceList
    path("price-lists/", view=views.price_list_list, name="price_list_list"),
    path("price-lists/<int:pk>/", view=views.price_list_detail, name="price_list_detail"),
]

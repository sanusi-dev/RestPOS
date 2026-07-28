from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", view=views.order_list, name="order_list"),
    path("<int:pk>/", view=views.order_detail, name="order_detail"),
    path("<int:pk>/cancel/", view=views.order_cancel, name="order_cancel"),
    path("kots/", view=views.kot_list, name="kot_list"),
]

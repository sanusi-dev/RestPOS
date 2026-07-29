from django.urls import path

from . import views_pos

app_name = "pos"

urlpatterns = [
    path("", view=views_pos.pos_home, name="pos_home"),
    path("order/new/", view=views_pos.pos_order_new, name="pos_order_new"),
    path("order/<int:pk>/add-item/", view=views_pos.pos_order_add_item, name="pos_order_add_item"),
    path("order/<int:pk>/sync/", view=views_pos.pos_order_sync, name="pos_order_sync"),
    path("order/<int:pk>/settle/", view=views_pos.pos_order_settle, name="pos_order_settle"),
    path("order/<int:pk>/cancel/", view=views_pos.pos_order_cancel, name="pos_order_cancel"),
]

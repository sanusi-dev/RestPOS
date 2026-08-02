from django.urls import path

from . import views_pos

app_name = "pos"

urlpatterns = [
    path("", view=views_pos.pos_home, name="pos_home"),
    path("history/", view=views_pos.pos_order_history, name="pos_order_history"),
    path("open-shift/", view=views_pos.pos_open_shift, name="pos_open_shift"),
    path("order/new/", view=views_pos.pos_order_new, name="pos_order_new"),
    path("order/<int:pk>/", view=views_pos.pos_order_screen, name="pos_order_screen"),
    path("order/<int:pk>/meta/", view=views_pos.pos_order_update_meta, name="pos_order_update_meta"),
    path("order/<int:pk>/add-item/", view=views_pos.pos_order_add_item, name="pos_order_add_item"),
    path(
        "order/<int:pk>/update-item/<int:item_pk>/", view=views_pos.pos_order_update_item, name="pos_order_update_item"
    ),
    path(
        "order/<int:pk>/customer-card/<int:idx>/",
        view=views_pos.pos_customer_card_activate,
        name="pos_customer_card_activate",
    ),
    path("order/<int:pk>/sync/", view=views_pos.pos_order_sync, name="pos_order_sync"),
    path("order/<int:pk>/clear/", view=views_pos.pos_order_clear, name="pos_order_clear"),
    path("order/<int:pk>/settle/", view=views_pos.pos_order_settle, name="pos_order_settle"),
    path("order/<int:pk>/cancel/", view=views_pos.pos_order_cancel, name="pos_order_cancel"),
    path("order/<int:pk>/print/", view=views_pos.pos_order_print, name="pos_order_print"),
    path(
        "order/<int:pk>/ticket/<str:ticket_type>/<str:action>/",
        view=views_pos.pos_order_ticket_print,
        name="pos_order_ticket_print",
    ),
]

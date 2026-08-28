"""URL configuration for the staff app."""

from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("", view=views.staff_dashboard, name="dashboard"),
    path("opening-entries/", view=views.opening_entry_list, name="opening_entry_list"),
    path(
        "opening-entries/create/",
        view=views.opening_entry_create,
        name="opening_entry_create",
    ),
    path(
        "opening-entries/<int:pk>/",
        view=views.opening_entry_detail,
        name="opening_entry_detail",
    ),
    path(
        "opening-entries/<int:pk>/submit/",
        view=views.opening_entry_submit,
        name="opening_entry_submit",
    ),
    path(
        "opening-entries/<int:pk>/cancel/",
        view=views.opening_entry_cancel,
        name="opening_entry_cancel",
    ),
    path("closing-entries/", view=views.closing_entry_list, name="closing_entry_list"),
    path(
        "closing-entries/create/",
        view=views.closing_entry_create,
        name="closing_entry_create",
    ),
    path(
        "closing-entries/<int:pk>/",
        view=views.closing_entry_detail,
        name="closing_entry_detail",
    ),
    path(
        "closing-entries/<int:pk>/submit/",
        view=views.closing_entry_submit,
        name="closing_entry_submit",
    ),
    path(
        "closing-entries/<int:pk>/cancel/",
        view=views.closing_entry_cancel,
        name="closing_entry_cancel",
    ),
]

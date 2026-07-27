"""URL configuration for the payments app."""

from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("", view=views.payments_dashboard, name="dashboard"),
    # ModeOfPayment
    path("modes/", view=views.mode_list, name="mode_list"),
    path("modes/create/", view=views.mode_create, name="mode_create"),
    path("modes/<int:pk>/", view=views.mode_detail, name="mode_detail"),
    path("modes/<int:pk>/edit/", view=views.mode_update, name="mode_update"),
    # PaymentGLMapping
    path("gl-mappings/", view=views.gl_mapping_list, name="gl_mapping_list"),
    path("gl-mappings/create/", view=views.gl_mapping_create, name="gl_mapping_create"),
    path("gl-mappings/<int:pk>/edit/", view=views.gl_mapping_update, name="gl_mapping_update"),
    path("gl-mappings/<int:pk>/delete/", view=views.gl_mapping_delete, name="gl_mapping_delete"),
]

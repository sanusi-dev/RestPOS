"""RestPOS root URL configuration."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # redirect Django admin login to main login page
    path("admin/login/", RedirectView.as_view(pattern_name="account_login")),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("users/", include("apps.users.urls")),
    path("backoffice/settings/", include("apps.settings.urls")),
    path("backoffice/inventory/", include("apps.inventory.urls")),
    path("backoffice/menu/", include("apps.menu.urls")),
    path("backoffice/payments/", include("apps.payments.urls")),
    path("backoffice/staff/", include("apps.staff.urls")),
    path("", include("apps.web.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Add browser reload URL if the middleware is enabled (matches middleware check in settings.py)
if "django_browser_reload.middleware.BrowserReloadMiddleware" in settings.MIDDLEWARE:
    urlpatterns.insert(0, path("__reload__/", include("django_browser_reload.urls")))

if settings.ENABLE_DEBUG_TOOLBAR:
    urlpatterns.append(path("__debug__/", include("debug_toolbar.urls")))

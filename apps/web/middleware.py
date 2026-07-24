import json

from django.contrib import messages as django_messages
from django.shortcuts import redirect

from apps.users.models import CustomUser


class BackofficeAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            path = request.path
            # On cashier/backoffice paths we always check role membership, so prefetch
            # the user's groups once and let cached_property role checks reuse them
            # (one groups query per request instead of ~9 groups.exists() per page).
            if path.startswith("/pos/") or path.startswith("/backoffice/"):
                request.user = CustomUser.objects.prefetch_related("groups").get(pk=request.user.pk)
            if path.startswith("/backoffice/") and not request.user.has_backoffice_access:
                return redirect("web:pos_index")
            if path.startswith("/pos/") and not request.user.has_staff_role:
                return redirect("web:pending_approval")
        return self.get_response(request)


class MessagesMiddleware:
    def __call__(self, request):
        response = self.get_response(request)
        self._inject_messages(request, response)
        return response

    def __init__(self, get_response):
        self.get_response = get_response

    def _inject_messages(self, request, response):
        if not request.htmx:
            return

        if not hasattr(request, "_messages"):
            return

        storage = django_messages.get_messages(request)
        message_list = [{"message": m.message, "level": m.level_tag} for m in storage]
        if not message_list:
            return

        trigger_data = json.loads(response.get("HX-Trigger", "{}"))
        trigger_data["showMessages"] = message_list
        response["HX-Trigger"] = json.dumps(trigger_data)

import json

from django.contrib import messages as django_messages


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

        # Preserve events emitted by the view while adding the message event
        # consumed by the toast listener.
        trigger_data = json.loads(response.get("HX-Trigger", "{}"))
        trigger_data["showMessages"] = message_list
        response["HX-Trigger"] = json.dumps(trigger_data)

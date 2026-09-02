import json

# The browser's XHR follows a 3xx and discards its headers, so an HX-Trigger
# toast attached to a redirect is never seen by HTMX.
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)


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

        storage = request._messages

        # A redirected HTMX request would swap the body (destroying the toast)
        # and the redirect's headers are dropped on follow. Rewrite it as a
        # 200 with HX-Redirect so HTMX performs a full navigation; the queued
        # messages persist in the cookie and render on the destination page.
        if response.status_code in _REDIRECT_STATUSES and storage:
            location = response.get("Location")
            if location:
                response.status_code = 200
                response["HX-Redirect"] = location
            return

        message_list = [{"message": m.message, "level": m.level_tag} for m in storage]
        if not message_list:
            return

        # Preserve events emitted by the view while adding the message event
        # consumed by the toast listener.
        trigger_data = json.loads(response.get("HX-Trigger", "{}"))
        trigger_data["showMessages"] = message_list
        response["HX-Trigger"] = json.dumps(trigger_data)

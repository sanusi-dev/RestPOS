import json

from django.contrib import messages as django_messages
from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.test import TestCase, override_settings
from django.urls import path, reverse


@login_not_required
def _redirect_with_message(request: HttpRequest) -> HttpResponseRedirect:
    """Set a success message and redirect — the pattern used by submit/cancel views."""
    django_messages.success(request, "Submitted.")
    return HttpResponseRedirect(reverse("mw-done"))


@login_not_required
def _redirect_without_message(request: HttpRequest) -> HttpResponseRedirect:
    return HttpResponseRedirect(reverse("mw-done"))


@login_not_required
def _plain_response_with_message(request: HttpRequest) -> HttpResponse:
    django_messages.error(request, "Something failed.")
    return HttpResponse("ok")


urlpatterns = [
    path("redirect-with-message/", _redirect_with_message, name="mw-redirect-with-message"),
    path("redirect-without-message/", _redirect_without_message, name="mw-redirect-without-message"),
    path("plain-with-message/", _plain_response_with_message, name="mw-plain-with-message"),
    path("done/", lambda request: HttpResponse("done"), name="mw-done"),
]


@override_settings(ROOT_URLCONF=__name__)
class MessagesMiddlewareTests(TestCase):
    def test_htmx_redirect_with_message_becomes_200_with_hx_redirect(self):
        response = self.client.post(reverse("mw-redirect-with-message"), HTTP_HX_REQUEST="true", HTTP_HX_BOOSTED="true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], reverse("mw-done"))
        self.assertNotIn("HX-Trigger", response)

    def test_htmx_plain_response_with_message_sets_trigger(self):
        response = self.client.get(reverse("mw-plain-with-message"), HTTP_HX_REQUEST="true")
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger["showMessages"][0]["message"], "Something failed.")
        self.assertEqual(trigger["showMessages"][0]["level"], "error")

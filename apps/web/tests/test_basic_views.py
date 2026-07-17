from django.urls import reverse

from .base import TestViewBase


class TestBasicViews(TestViewBase):
    def test_home_redirects_to_login(self):
        response = self.client.get(reverse("web:home"))
        self.assertRedirects(response, reverse("account_login"))

    def test_signup(self):
        self._assert_200(reverse("account_signup"))

    def test_login(self):
        self._assert_200(reverse("account_login"))

    def _assert_200(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class HelpCenterTests(TestCase):
    def test_help_requires_authentication(self):
        response = self.client.get(reverse("helpcenter:home"))

        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('helpcenter:home')}",
        )

    def test_help_page_lists_categories_and_faqs(self):
        user = get_user_model().objects.create_user(
            username="help-user",
            password="test-password",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("helpcenter:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "How do I read a notification?")
        self.assertContains(response, "Getting started")

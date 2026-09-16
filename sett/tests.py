from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import Organization, OrganizationMembership
from sett.models import Workspace

User = get_user_model()


class WorkspaceBackendTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="manager_test",
            email="manager@test.com",
            password="password123",
            role=User.Role.MANAGER,
            display_name="Test Manager",
        )
        self.organization = Organization.objects.create(
            name="Initial Org",
            slug="initial-org",
            created_by=self.user,
        )
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.organization,
            role=OrganizationMembership.Role.MANAGER,
        )
        self.client.login(username="manager_test", password="password123")

    def test_workspace_get_for_user_initialization(self):
        workspace = Workspace.get_for_user(self.user)
        self.assertIsNotNone(workspace)
        self.assertEqual(workspace.user, self.user)
        self.assertEqual(workspace.organization, self.organization)
        self.assertEqual(workspace.name, "Initial Org")
        self.assertEqual(workspace.role, "Freelance Designer & Developer")
        self.assertEqual(workspace.currency, "NPR")

    def test_workspace_settings_get_page(self):
        response = self.client.get(reverse("sett:settings") + "?tab=workspace")
        self.assertEqual(response.status_code, 200)
        self.assertIn("workspace", response.context)
        self.assertContains(response, "Initial Org")
        self.assertContains(response, "Freelance Designer &amp; Developer")
        self.assertContains(response, 'value="NPR" selected')
        self.assertEqual(response.context["workspace"].role, "Freelance Designer & Developer")

    def test_workspace_save_post(self):
        post_data = {
            "action": "workspace",
            "workspace_name": "Rivera Studio",
            "role": "Lead Product Designer",
            "currency": "USD",
        }
        response = self.client.post(reverse("sett:settings"), data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/settings/?tab=workspace"))

        # Verify database record updated
        workspace = Workspace.objects.get(user=self.user)
        self.assertEqual(workspace.name, "Rivera Studio")
        self.assertEqual(workspace.role, "Lead Product Designer")
        self.assertEqual(workspace.currency, "USD")

        # Verify organization name synchronized
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Rivera Studio")

    def test_workspace_save_ajax_post(self):
        post_data = {
            "action": "workspace",
            "workspace_name": "Acme Creative Lab",
            "role": "Freelance Designer & Developer",
            "currency": "EUR",
        }
        response = self.client.post(
            reverse("sett:settings"),
            data=post_data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["workspace"]["name"], "Acme Creative Lab")
        self.assertEqual(data["workspace"]["role"], "Freelance Designer & Developer")
        self.assertEqual(data["workspace"]["currency"], "EUR")

        workspace = Workspace.objects.get(user=self.user)
        self.assertEqual(workspace.name, "Acme Creative Lab")
        self.assertEqual(workspace.currency, "EUR")

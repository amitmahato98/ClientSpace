from django.conf import settings
from django.db import models


class Workspace(models.Model):
    """
    Persisted workspace preferences for ClientSpace settings.
    Stores the studio/workspace name, user role title, and chosen currency.
    """

    CURRENCY_CHOICES = [
        ("NPR", "NPR - Nepalese Rupee"),
        ("USD", "$ USD"),
        ("EUR", "€ EUR"),
        ("INR", "₹ INR — Indian Rupee"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_profile",
    )

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspaces",
    )

    name = models.CharField(
        max_length=200,
        default="Rivera Studio",
        verbose_name="Studio / Workspace name",
    )

    role = models.CharField(
        max_length=150,
        default="Freelance Designer & Developer",
        verbose_name="Your role",
    )

    currency = models.CharField(
        max_length=10,
        choices=CURRENCY_CHOICES,
        default="NPR",
        verbose_name="Currency",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Workspace Setting"
        verbose_name_plural = "Workspace Settings"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.name} ({self.user.username})"

    @classmethod
    def get_for_user(cls, user):
        """
        Retrieve or initialize the Workspace record for a given user.
        Syncs initial workspace name with the user's Organization if available.
        """
        from accounts.models import OrganizationMembership

        workspace, created = cls.objects.get_or_create(user=user)
        membership = (
            OrganizationMembership.objects.filter(user=user)
            .select_related("organization")
            .first()
        )

        needs_save = False
        if membership and membership.organization:
            if workspace.organization != membership.organization:
                workspace.organization = membership.organization
                needs_save = True

            # If newly created and organization has a name, use it
            if created and membership.organization.name:
                workspace.name = membership.organization.name
                needs_save = True

        if needs_save:
            workspace.save()

        return workspace

from django.conf import settings
from django.db import models


class Payment(models.Model):
    STATUS_CHOICES = [
        ('paid', 'Paid'),
        ('pending', 'Pending'),
        ('failed', 'Failed'),
    ]

    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payments',
        limit_choices_to={'role': 'CLIENT'},
    )
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments',
    )
    date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='paid')

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.client.username} — ₹{self.amount} ({self.status})"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if (is_new or self.status == 'paid') and self.status == 'paid':
            try:
                from notifications.service import notify_payment_received
                from accounts.models import OrganizationMembership
                from django.contrib.auth import get_user_model
                User = get_user_model()
                # Notify managers of client's organization
                membership = OrganizationMembership.objects.filter(
                    user=self.client,
                    role=OrganizationMembership.Role.CLIENT,
                ).first()
                if membership and membership.organization:
                    managers = OrganizationMembership.objects.filter(
                        organization=membership.organization,
                        role=OrganizationMembership.Role.MANAGER,
                    ).values_list("user_id", flat=True)
                    for mgr_id in managers:
                        try:
                            mgr = User.objects.get(pk=mgr_id)
                            notify_payment_received(
                                recipient=mgr,
                                client=self.client,
                                amount=self.amount,
                                project=self.project,
                            )
                        except User.DoesNotExist:
                            continue
            except Exception:
                pass



class Note(models.Model):
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notes',
        limit_choices_to={'role': 'CLIENT'},
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authored_notes',
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note on {self.client.username} ({self.created_at.date()})"


class ClientActivity(models.Model):
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='activities',
        limit_choices_to={'role': 'CLIENT'},
    )
    description = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = 'Client activities'

    def __str__(self):
        return f"{self.client.username}: {self.description}"
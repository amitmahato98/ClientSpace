from django.db import models
from django.conf import settings


class Client(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('pending', 'Pending'),
        ('archived', 'Archived'),
    ]

    name = models.CharField(max_length=150)
    company = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    client_since = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def initials(self):
        parts = self.name.split()
        return (parts[0][0] + parts[1][0]).upper() if len(parts) > 1 else parts[0][0].upper()

    # ---- Financial Summary (computed, not stored) ----
    @property
    def total_billed(self):
        return sum(p.value for p in self.projects.all())

    @property
    def total_paid(self):
        return sum(p.amount for p in self.payments.filter(status='paid'))

    @property
    def outstanding(self):
        return self.total_billed - self.total_paid


class Project(models.Model):
    STATUS_CHOICES = [
        ('on_track', 'On track'),
        ('at_risk', 'At risk'),
        ('blocked', 'Blocked'),
        ('planning', 'Planning'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='projects')
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='planning')
    value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.client.name})"


class Payment(models.Model):
    STATUS_CHOICES = [
        ('paid', 'Paid'),
        ('pending', 'Pending'),
        ('failed', 'Failed'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='payments')
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='paid')

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.client.name} — ₹{self.amount} ({self.status})"


class Note(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='notes')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note on {self.client.name} ({self.created_at.date()})"


class ClientActivity(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='activities')
    description = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = 'Client activities'

    def __str__(self):
        return f"{self.client.name}: {self.description}"
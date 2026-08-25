from django.db import models

# Create your models here.

from django.db import models

class Client(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('pending', 'Pending'),
        ('archived', 'Archived'),
    ]

    name = models.CharField(max_length=150)
    industry = models.CharField(max_length=150, blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    contact_email = models.EmailField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    client_since = models.DateField(null=True, blank=True)
    lifetime_billed = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def initials(self):
        """Used for the colored avatar circle in the template, e.g. 'Alden & Co.' -> 'A'"""
        parts = self.name.split()
        return (parts[0][0] + parts[1][0]).upper() if len(parts) > 1 else parts[0][0].upper()






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
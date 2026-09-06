from django.db import models
from django.conf import settings


class Staff(models.Model):

    ROLE_CHOICES = [
        ("Developer", "Developer"),
        ("Designer", "Designer"),
        ("Tester", "Tester"),
        ("Manager", "Manager"),
    ]

    STATUS_CHOICES = [
        ("Available", "Available"),
        ("Working", "Working"),
        ("On Leave", "On Leave"),
    ]

    # Staff member's login account
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
        null=True,
        blank=True
    )

    # Person who added/created this staff
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_staff"
    )

    # Organization the staff belongs to
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="staff"
    )

    first_name = models.CharField(max_length=100)

    last_name = models.CharField(max_length=100)

    phone = models.CharField(
        max_length=15,
        blank=True
    )
    email = models.EmailField(null=True)

    # Staff's actual job position
    role = models.CharField(
        max_length=50,
        choices=ROLE_CHOICES
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Available"
    )

    # Project assigned to the staff
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class StaffAssignment(models.Model):

    staff = models.ForeignKey(
        Staff,
        on_delete=models.CASCADE,
        related_name="assignments"
    )

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="staff_assignments"
    )

    work = models.TextField()

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="staff_assignments_created"
    )

    assigned_at = models.DateTimeField(
        auto_now_add=True
    )

    is_active = models.BooleanField(
        default=True
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    def __str__(self):
        return f"{self.staff} - {self.project}"


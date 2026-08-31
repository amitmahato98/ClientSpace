from django.conf import settings
from django.db import models


class Project(models.Model):
    """
    Core project entity for ClientSpace.

    A project belongs to a Client (from the clients app) and is created
    by a Manager user.  Status and Priority use TextChoices so values are
    validated at the model level and human-readable labels are available
    in templates via get_FOO_display().
    """

    class Status(models.TextChoices):
        PLANNING    = "PLANNING",    "Planning"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        AT_RISK     = "AT_RISK",     "At Risk"
        BLOCKED     = "BLOCKED",     "Blocked"
        COMPLETED   = "COMPLETED",   "Completed"
        ON_HOLD     = "ON_HOLD",     "On Hold"

    class Priority(models.TextChoices):
        LOW    = "LOW",    "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH   = "HIGH",   "High"

    name = models.CharField(max_length=200)

    description = models.TextField(blank=True)

    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="main_projects",   # avoids clash with clients.Project.client FK
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNING,
    )

    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )

    budget = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Total project budget",
    )

    start_date = models.DateField(null=True, blank=True)

    deadline = models.DateField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_projects",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Project"
        verbose_name_plural = "Projects"

    def __str__(self):
        client_name = self.client.name if self.client else "No client"
        return f"{self.name} ({client_name})"

    # ------------------------------------------------------------------ #
    # Convenience helpers used in templates                               #
    # ------------------------------------------------------------------ #

    @property
    def status_css_class(self):
        """
        Returns the Tailwind badge CSS classes matching the existing UI
        colour scheme so templates stay clean.
        """
        return {
            self.Status.PLANNING:    "bg-[#e8f0fe] text-[#1a73e8]",
            self.Status.IN_PROGRESS: "bg-[#e6f4ea] text-[#137333]",
            self.Status.AT_RISK:     "bg-[#fef7e0] text-[#b06000]",
            self.Status.BLOCKED:     "bg-[#fce8e6] text-[#c5221f]",
            self.Status.COMPLETED:   "bg-[#e6f4ea] text-[#137333]",
            self.Status.ON_HOLD:     "bg-[#f3f4f6] text-[#6b7280]",
        }.get(self.status, "bg-gray-100 text-gray-600")

    @property
    def status_data_value(self):
        """
        Returns the lowercase hyphenated value used by the JS filter system
        in the existing projects.html (data-status attribute).
        """
        return {
            self.Status.PLANNING:    "planning",
            self.Status.IN_PROGRESS: "on-track",
            self.Status.AT_RISK:     "at-risk",
            self.Status.BLOCKED:     "blocked",
            self.Status.COMPLETED:   "on-track",
            self.Status.ON_HOLD:     "planning",
        }.get(self.status, "planning")

from django.conf import settings
from django.db import models


# ═══════════════════════════════════════════════════════════════════════════
# Task
# ═══════════════════════════════════════════════════════════════════════════

class Task(models.Model):
    """
    A unit of work belonging to a Project and assigned to a Staff member.

    Authorization chain
    ───────────────────
    Task → project → organization  (no duplicate org FK needed)

    Assignment constraint (enforced in TaskForm, not at DB level)
    ─────────────────────────────────────────────────────────────
    assigned_to must be a User whose Staff profile has an *active*
    StaffAssignment to the same project.  This is validated server-side
    in TaskForm so crafted POST requests cannot bypass the restriction.

    Phase 3 hook points
    ────────────────────
    task_create  → "Task created and assigned to <staff>"
    task_edit    → "Task reassigned to <new staff>" or "Status changed to …"
    task_status_update → "Task marked <status> by <staff>"
    """

    class Status(models.TextChoices):
        PENDING     = "PENDING",     "Pending"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        COMPLETED   = "COMPLETED",   "Completed"

    class Priority(models.TextChoices):
        LOW    = "LOW",    "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH   = "HIGH",   "High"

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="tasks",
    )

    # Points to the STAFF user assigned to this task.
    # SET_NULL so deleting a user account does not cascade-delete the task record.
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
        limit_choices_to={"role": "STAFF"},
    )

    title = models.CharField(max_length=200)

    description = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )

    due_date = models.DateField(null=True, blank=True)

    # The Manager who created this task — set server-side, never from POST.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tasks",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_date", "-priority", "title"]
        verbose_name = "Task"
        verbose_name_plural = "Tasks"

    def __str__(self):
        assignee = self.assigned_to.get_full_name() if self.assigned_to else "Unassigned"
        return f"{self.title} ({self.project.name} → {assignee})"

    # ------------------------------------------------------------------ #
    # Template helpers                                                     #
    # ------------------------------------------------------------------ #

    @property
    def status_css_class(self):
        return {
            self.Status.PENDING:     "bg-[#f3f4f6] text-[#6b7280]",
            self.Status.IN_PROGRESS: "bg-[#e8f0fe] text-[#1a73e8]",
            self.Status.COMPLETED:   "bg-[#e6f4ea] text-[#137333]",
        }.get(self.status, "bg-gray-100 text-gray-600")

    @property
    def priority_css_class(self):
        return {
            self.Priority.HIGH:   "bg-[#fce8e6] text-[#c5221f]",
            self.Priority.MEDIUM: "bg-[#fef7e0] text-[#b06000]",
            self.Priority.LOW:    "bg-[#edf0f4] text-[#657084]",
        }.get(self.priority, "bg-gray-100 text-gray-600")

    @property
    def assigned_display_name(self):
        if not self.assigned_to:
            return "Unassigned"
        full = self.assigned_to.get_full_name()
        return full.strip() if full.strip() else self.assigned_to.username


class Project(models.Model):
    """
    Core project entity for ClientSpace.

    A project is associated with a Client user (accounts.User, role=CLIENT)
    and is created by a Manager user.  The client FK points directly at
    the AUTH_USER_MODEL so no separate Client table is needed.

    Status and Priority use TextChoices so values are validated at the model
    level and human-readable labels are available in templates via
    get_FOO_display().
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

    # The organisation this project belongs to — derived from the creating
    # Manager's membership.  SET_NULL so deleting an org record does not
    # cascade-delete all its projects (data preservation).
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects",
    )

    # Points to the CLIENT user created automatically during project creation.
    # SET_NULL so deleting a client account does not cascade-delete the project.
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="client_projects",
        limit_choices_to={"role": "CLIENT"},
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

    # The Manager who created this project — set server-side, never from POST.
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
        client_name = self.client.username if self.client else "No client"
        return f"{self.name} ({client_name})"

    # ------------------------------------------------------------------ #
    # Convenience helpers used in templates                               #
    # ------------------------------------------------------------------ #

    @property
    def client_display_name(self):
        """Human-readable client name for templates."""
        if not self.client:
            return "No client assigned"
        full = self.client.get_full_name()
        return full if full.strip() else self.client.username

    @property
    def status_css_class(self):
        """Tailwind badge CSS classes matching the existing UI colour scheme."""
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
        """Lowercase hyphenated value for the JS filter system (data-status attr)."""
        return {
            self.Status.PLANNING:    "planning",
            self.Status.IN_PROGRESS: "on-track",
            self.Status.AT_RISK:     "at-risk",
            self.Status.BLOCKED:     "blocked",
            self.Status.COMPLETED:   "on-track",
            self.Status.ON_HOLD:     "planning",
        }.get(self.status, "planning")


# ═══════════════════════════════════════════════════════════════════════════
# ProjectActivity — permanent audit trail for a project
# ═══════════════════════════════════════════════════════════════════════════

class ProjectActivity(models.Model):
    """
    Immutable record of a single action that occurred inside a project.

    Design notes
    ────────────
    • Records are append-only — never edited or deleted by application code.
    • The description is the fully-rendered human-readable string stored at
      creation time so it remains accurate even if referenced objects are
      later renamed or deleted.
    • actor is SET_NULL (not CASCADE) so deleting a user does not remove
      historical audit records.
    • Visibility: MANAGER and STAFF see all activities; CLIENT sees nothing
      (enforced in the template and in project_detail context).

    Phase hook points
    ─────────────────
    PROJECT_CREATED  → project_create view
    STAFF_ASSIGNED   → assign_staff view
    STAFF_REMOVED    → remove_staff view
    TASK_ADDED       → task_create view
    TASK_UPDATED     → task_edit view
    TASK_STATUS      → task_status_update view
    TASK_DELETED     → task_delete view
    """

    class ActionType(models.TextChoices):
        PROJECT_CREATED = "PROJECT_CREATED", "Project Created"
        STAFF_ASSIGNED  = "STAFF_ASSIGNED",  "Staff Assigned"
        STAFF_REMOVED   = "STAFF_REMOVED",   "Staff Removed"
        TASK_ADDED      = "TASK_ADDED",      "Task Added"
        TASK_UPDATED    = "TASK_UPDATED",    "Task Updated"
        TASK_STATUS     = "TASK_STATUS",     "Task Status Changed"
        TASK_DELETED    = "TASK_DELETED",    "Task Deleted"

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="activities",
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="project_activities",
    )

    action_type = models.CharField(
        max_length=30,
        choices=ActionType.choices,
    )

    # Fully-rendered human-readable sentence stored at creation time.
    description = models.CharField(max_length=500)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Project Activity"
        verbose_name_plural = "Project Activities"

    def __str__(self):
        return f"[{self.project.name}] {self.description}"

    # ------------------------------------------------------------------ #
    # Icon helper for the timeline UI                                     #
    # ------------------------------------------------------------------ #

    @property
    def icon_css(self):
        """Font Awesome icon class + background colour for the timeline dot."""
        mapping = {
            self.ActionType.PROJECT_CREATED: ("fa-plus",        "bg-[#e8f0fe] text-[#1a73e8]"),
            self.ActionType.STAFF_ASSIGNED:  ("fa-user-plus",   "bg-[#e6f4ea] text-[#137333]"),
            self.ActionType.STAFF_REMOVED:   ("fa-user-minus",  "bg-[#fce8e6] text-[#c5221f]"),
            self.ActionType.TASK_ADDED:      ("fa-tasks",       "bg-[#f5e6d0] text-[#8b6f55]"),
            self.ActionType.TASK_UPDATED:    ("fa-pen",         "bg-[#fef7e0] text-[#b06000]"),
            self.ActionType.TASK_STATUS:     ("fa-check-circle","bg-[#e6f4ea] text-[#137333]"),
            self.ActionType.TASK_DELETED:    ("fa-trash-alt",   "bg-[#fce8e6] text-[#c5221f]"),
        }
        icon, bg = mapping.get(self.action_type, ("fa-circle", "bg-gray-100 text-gray-500"))
        return {"icon": icon, "bg": bg}

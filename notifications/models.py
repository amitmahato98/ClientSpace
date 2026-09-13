from django.conf import settings
from django.db import models


class Notification(models.Model):
    """
    A single in-app notification for one user.

    Design notes
    ────────────
    • recipient  — the user who will see this notification.
    • actor      — the user who triggered the action (nullable so system
                   events can be generated without an actor).
    • message    — the human-readable text shown in the dropdown.
    • link       — where the user is redirected when they click the item.
    • is_read    — False until the user clicks the notification or uses
                   "Mark all as read".
    • created_at — used for ordering (newest first).

    Security
    ────────
    All views that interact with Notification records must verify
    request.user == notification.recipient before reading or mutating.

    Phase 3 hook points already exist in projects/views.py:
      Event A — assign_staff      → notify staff user
      Event B — task_create       → notify assigned staff user
      Event C — task_status_update → notify project manager(s)
    """

    class NotificationType(models.TextChoices):
        PAYMENT_RECEIVED = "payment_received", "Payment received"
        DEADLINE_REMINDER = "deadline_reminder", "Deadline reminder"
        OVERDUE_ALERT = "overdue_alert", "Overdue alert"
        CLIENT_PORTAL_VIEWED = "client_portal_viewed", "Client portal viewed"
        TEAM_MEMBER_JOINED = "team_member_joined", "Team member joined"
        WEEKLY_SUMMARY = "weekly_summary", "Weekly summary"
        ACCOUNT_ACTIVITY = "account_activity", "Account activity"
        TASK_ASSIGNED = "task_assigned", "Task assigned"
        PROJECT_ASSIGNED = "project_assigned", "Project assigned"
        GENERAL = "general", "General"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    # Who triggered the action — nullable for system-generated events.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_notifications",
    )

    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
        db_index=True,
    )

    message = models.CharField(max_length=500)

    # Absolute path (e.g. /projects/3/) or full URL — stored as a plain
    # CharField so it works with both relative and absolute links.
    link = models.CharField(max_length=500, blank=True, default="")

    is_read = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self):
        status = "read" if self.is_read else "unread"
        return f"[{status}] [{self.notification_type}] → {self.recipient.username}: {self.message[:60]}"


class NotificationSetting(models.Model):
    """
    User notification preferences corresponding to the Settings -> Notifications panel.
    All notification settings default to True (ON).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_settings",
    )

    # Corresponds to Settings toggles
    payment_received = models.BooleanField(default=True)
    deadline_reminder = models.BooleanField(default=True)
    overdue_alert = models.BooleanField(default=True)
    client_portal_viewed = models.BooleanField(default=True)
    team_member_joined = models.BooleanField(default=True)
    weekly_summary = models.BooleanField(default=True)
    account_activity = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification Setting"
        verbose_name_plural = "Notification Settings"

    def __str__(self):
        return f"NotificationSettings({self.user.username})"

    def is_enabled(self, notification_type: str) -> bool:
        """
        Check if the specified notification type is enabled.
        Unknown or general types return True by default.
        """
        if not notification_type:
            return True
        return getattr(self, notification_type, True)

    def get_disabled_types(self) -> list[str]:
        """
        Return list of notification type keys currently turned OFF.
        """
        keys = [
            "payment_received",
            "deadline_reminder",
            "overdue_alert",
            "client_portal_viewed",
            "team_member_joined",
            "weekly_summary",
            "account_activity",
        ]
        return [k for k in keys if not getattr(self, k, True)]



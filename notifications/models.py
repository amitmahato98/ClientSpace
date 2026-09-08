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
        return f"[{status}] → {self.recipient.username}: {self.message[:60]}"

"""
notifications/context_processors.py
────────────────────────────────────
Injects notification data into every template rendered by the Django
template engine.  This means base.html can display the unread count and
recent notifications on every page without each view needing to pass them
explicitly.

Registered in settings.py → TEMPLATES[0]["OPTIONS"]["context_processors"].

Variables injected
──────────────────
  notification_list   — QuerySet of the 10 most-recent notifications for
                        the current user (read + unread), ordered newest first.
  unread_count        — integer count of unread notifications for the badge.

Both variables are set to safe empty values for anonymous users or users
with no notifications, so templates can always reference them safely.
"""


def notifications(request):
    """
    Return notification context for the authenticated user.

    Returns empty defaults for anonymous users so templates never throw
    AttributeError / VariableDoesNotExist errors.
    """
    if not request.user.is_authenticated:
        return {
            "notification_list": [],
            "unread_count": 0,
        }

    try:
        from .models import Notification

        qs = (
            Notification.objects
            .filter(recipient=request.user)
            .select_related("actor")
            .order_by("-created_at")
        )

        unread_count    = qs.filter(is_read=False).count()
        notification_list = qs[:10]  # cap at 10 for the dropdown

        return {
            "notification_list": notification_list,
            "unread_count": unread_count,
        }

    except Exception:
        # If the table doesn't exist yet (e.g. before first migration),
        # return safe empty values rather than crashing every page.
        return {
            "notification_list": [],
            "unread_count": 0,
        }

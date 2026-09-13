from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from .models import Notification, NotificationSetting


def _get_active_notifications_qs(user):
    """
    Helper to get the notifications queryset for a user excluding disabled types.
    """
    settings_obj, _ = NotificationSetting.objects.get_or_create(user=user)
    disabled_types = settings_obj.get_disabled_types()
    qs = Notification.objects.filter(recipient=user)
    if disabled_types:
        qs = qs.exclude(notification_type__in=disabled_types)
    return qs


@login_required
def notification_click(request, pk):
    """
    Mark a single notification as read and redirect to its link.

    Security: verifies request.user == notification.recipient.
    Any other user gets a 404 (not a 403, to avoid leaking existence).

    Accepts GET so navbar anchor <a href="..."> links work without a form.
    """
    notification = get_object_or_404(
        Notification,
        pk=pk,
        recipient=request.user,    # ownership check
    )

    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])

    # Redirect to the stored link, fallback to home if empty.
    destination = notification.link or "/"
    return redirect(destination)


@login_required
def mark_all_read(request):
    """
    Mark ALL of the current user's visible unread notifications as read.

    POST only — mutates state so GET is refused.
    """
    if request.method != "POST":
        return redirect("/")

    _get_active_notifications_qs(request.user).filter(
        is_read=False,
    ).update(is_read=True)

    messages.success(request, "All notifications marked as read.")

    # Return to the page the user was on, falling back to home.
    referer = request.META.get("HTTP_REFERER", "/")
    return redirect(referer)


@login_required
def notification_list(request):
    """
    Full notifications page — shows all active notifications for the current user,
    with a "Mark all as read" button.

    Only the current user's enabled notifications are returned.
    """
    notifications = (
        _get_active_notifications_qs(request.user)
        .select_related("actor")
        .order_by("-created_at")
    )

    unread_count = notifications.filter(is_read=False).count()

    return render(request, "notifications/notification_list.html", {
        "notifications": notifications,
        "unread_count": unread_count,
    })


# ──────────────────────────────────────────────────────────────────────────────
# AJAX ENDPOINTS — Phase 5
# ──────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["POST"])
def mark_single_read_ajax(request, pk):
    """
    AJAX endpoint: mark a single notification as read.

    Returns JSON: {"success": true, "unread_count": <int>}

    Security: verifies request.user == notification.recipient (returns 404 on mismatch).
    """
    notification = get_object_or_404(
        Notification,
        pk=pk,
        recipient=request.user,
    )

    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])

    unread_count = _get_active_notifications_qs(request.user).filter(
        is_read=False,
    ).count()

    return JsonResponse({
        "success": True,
        "unread_count": unread_count,
    })


@login_required
@require_http_methods(["POST"])
def mark_all_read_ajax(request):
    """
    AJAX endpoint: mark ALL of the current user's visible unread notifications as read.

    Returns JSON: {"success": true, "unread_count": 0}
    """
    _get_active_notifications_qs(request.user).filter(
        is_read=False,
    ).update(is_read=True)

    return JsonResponse({
        "success": True,
        "unread_count": 0,
    })


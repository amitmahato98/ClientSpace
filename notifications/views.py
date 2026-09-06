from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages

from .models import Notification


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
    Mark ALL of the current user's unread notifications as read.

    POST only — mutates state so GET is refused.
    """
    if request.method != "POST":
        return redirect("/")

    Notification.objects.filter(
        recipient=request.user,
        is_read=False,
    ).update(is_read=True)

    messages.success(request, "All notifications marked as read.")

    # Return to the page the user was on, falling back to home.
    referer = request.META.get("HTTP_REFERER", "/")
    return redirect(referer)


@login_required
def notification_list(request):
    """
    Full notifications page — shows all notifications for the current user,
    with a "Mark all as read" button.

    Only the current user's notifications are returned — the queryset is
    scoped to recipient=request.user.
    """
    notifications = (
        Notification.objects
        .filter(recipient=request.user)
        .select_related("actor")
        .order_by("-created_at")
    )

    unread_count = notifications.filter(is_read=False).count()

    return render(request, "notifications/notification_list.html", {
        "notifications": notifications,
        "unread_count": unread_count,
    })

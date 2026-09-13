"""
notifications/service.py
────────────────────────
Thin service layer for creating Notification records.

All notification-creation logic is centralised here so:
  • Views stay clean — one-line calls with clear intent.
  • Phase 4+ can swap in email / push / WebSocket delivery here without
    touching views at all.
  • Tests can mock a single import point.

Usage in views
──────────────
    from notifications.service import notify_staff_assigned_to_project
    notify_staff_assigned_to_project(actor=request.user, staff_user=user, project=project)
"""

import logging

from django.urls import reverse

logger = logging.getLogger(__name__)


def _create(*, recipient, actor, message, link="", notification_type="general"):
    """
    Internal helper. Imports Notification lazily to avoid circular
    imports at module load time (the model imports settings.AUTH_USER_MODEL).
    Swallows exceptions so a notification failure never breaks the primary action.

    CRITICAL: Checks recipient's NotificationSetting. If notification_type is turned OFF,
    creation is suppressed and None is returned.
    """
    if recipient is None:
        return None

    try:
        from .models import Notification, NotificationSetting

        # Verify whether the recipient wants to receive this type of notification
        settings_obj, _ = NotificationSetting.objects.get_or_create(user=recipient)
        if not settings_obj.is_enabled(notification_type):
            logger.info(
                "Notification of type '%s' suppressed for user %s (setting turned OFF)",
                notification_type,
                recipient.username,
            )
            return None

        return Notification.objects.create(
            recipient=recipient,
            actor=actor,
            message=message,
            link=link,
            notification_type=notification_type,
        )
    except Exception as exc:
        logger.error("Failed to create notification for %s: %s", recipient, exc)
        return None


# ────────────────────────────────────────────────────────────────────────────
# Event A — Staff assigned to a project  (Phase 1 hook point)
# ────────────────────────────────────────────────────────────────────────────

def notify_staff_assigned_to_project(*, actor, staff_user, project):
    """
    Notify a Staff member that they have been assigned to a project.
    """
    if staff_user is None:
        return
    link = reverse("projects:project_detail", kwargs={"pk": project.pk})
    _create(
        recipient=staff_user,
        actor=actor,
        message=f"You have been assigned to the project: {project.name}.",
        link=link,
        notification_type="project_assigned",
    )


# ────────────────────────────────────────────────────────────────────────────
# Event B — Task assigned to Staff  (Phase 2 hook point)
# ────────────────────────────────────────────────────────────────────────────

def notify_task_assigned(*, actor, task):
    """
    Notify the assigned Staff member that a new task has been created for them.
    """
    staff_user = task.assigned_to
    if staff_user is None:
        return
    link = reverse("projects:my_tasks")
    _create(
        recipient=staff_user,
        actor=actor,
        message=(
            f"You have a new task: \"{task.title}\" "
            f"in {task.project.name}."
        ),
        link=link,
        notification_type="task_assigned",
    )


# ────────────────────────────────────────────────────────────────────────────
# Event B (edit) — Task reassigned to a different Staff member
# ────────────────────────────────────────────────────────────────────────────

def notify_task_reassigned(*, actor, task, previous_user):
    """
    Notify the new assignee when a task is reassigned by a Manager.
    """
    new_user = task.assigned_to
    if new_user is None:
        return
    link = reverse("projects:my_tasks")
    _create(
        recipient=new_user,
        actor=actor,
        message=(
            f"You have been assigned the task: \"{task.title}\" "
            f"in {task.project.name}."
        ),
        link=link,
        notification_type="task_assigned",
    )


# ────────────────────────────────────────────────────────────────────────────
# Event C — Task status updated by Staff  (Phase 2 hook point)
# ────────────────────────────────────────────────────────────────────────────

def notify_task_status_updated(*, actor, task):
    """
    Notify the project's Manager(s) when a Staff member updates a task status.
    """
    project = task.project
    if project.organization is None:
        return

    from accounts.models import OrganizationMembership

    manager_users = (
        OrganizationMembership.objects
        .filter(
            organization=project.organization,
            role=OrganizationMembership.Role.MANAGER,
        )
        .select_related("user")
        .values_list("user", flat=True)
    )

    actor_name = actor.get_full_name().strip() or actor.username
    link = reverse("projects:project_detail", kwargs={"pk": project.pk})

    from django.contrib.auth import get_user_model
    User = get_user_model()

    for manager_id in manager_users:
        try:
            manager = User.objects.get(pk=manager_id)
        except User.DoesNotExist:
            continue
        _create(
            recipient=manager,
            actor=actor,
            message=(
                f"{actor_name} marked \"{task.title}\" "
                f"as {task.get_status_display()} "
                f"in {project.name}."
            ),
            link=link,
            notification_type="task_assigned",
        )


# ────────────────────────────────────────────────────────────────────────────
# Settings Notification Events:
# 1. Payment received
# 2. Deadline reminder
# 3. Overdue alert
# 4. Client portal viewed
# 5. Team member joined
# 6. Weekly summary
# ────────────────────────────────────────────────────────────────────────────

def notify_payment_received(*, recipient, client, amount, project=None, actor=None):
    """
    Notify recipient (e.g. manager) when a client payment is recorded.
    """
    client_name = client.get_full_name().strip() or client.username
    proj_text = f" for {project.name}" if project else ""
    link = reverse("clients") + f"?client={client.pk}"
    return _create(
        recipient=recipient,
        actor=actor,
        message=f"Payment received: ₹{amount} from {client_name}{proj_text}.",
        link=link,
        notification_type="payment_received",
    )


def notify_deadline_reminder(*, recipient, project, days_left=2, actor=None):
    """
    Notify recipient when a project deadline is approaching (e.g. 2 days away).
    """
    link = reverse("projects:project_detail", kwargs={"pk": project.pk})
    return _create(
        recipient=recipient,
        actor=actor,
        message=f"Deadline reminder: \"{project.name}\" is due in {days_left} days.",
        link=link,
        notification_type="deadline_reminder",
    )


def notify_overdue_alert(*, recipient, project, actor=None):
    """
    Notify recipient when a project has passed its deadline.
    """
    link = reverse("projects:project_detail", kwargs={"pk": project.pk})
    return _create(
        recipient=recipient,
        actor=actor,
        message=f"Overdue alert: Project \"{project.name}\" has passed its deadline.",
        link=link,
        notification_type="overdue_alert",
    )


def notify_client_portal_viewed(*, recipient, client, project=None, actor=None):
    """
    Notify manager when a client opens their portal.
    """
    client_name = client.get_full_name().strip() or client.username
    if project:
        msg = f"Client portal viewed: {client_name} opened the portal for {project.name}."
        link = reverse("projects:project_detail", kwargs={"pk": project.pk})
    else:
        msg = f"Client portal viewed: {client_name} opened their client portal."
        link = reverse("projects:project_list")

    return _create(
        recipient=recipient,
        actor=actor or client,
        message=msg,
        link=link,
        notification_type="client_portal_viewed",
    )


def notify_team_member_joined(*, staff_member, actor=None):
    """
    Notify all Managers in the organization when a staff member accepts their invite.
    """
    organization = staff_member.organization
    if not organization:
        return []

    from accounts.models import OrganizationMembership
    from django.contrib.auth import get_user_model
    User = get_user_model()

    manager_user_ids = (
        OrganizationMembership.objects
        .filter(
            organization=organization,
            role=OrganizationMembership.Role.MANAGER,
        )
        .values_list("user_id", flat=True)
    )

    staff_name = f"{staff_member.first_name} {staff_member.last_name}".strip() or "A new team member"
    job_role = staff_member.role or "staff"
    link = reverse("staff")

    created_notifs = []
    for manager_id in manager_user_ids:
        try:
            manager = User.objects.get(pk=manager_id)
        except User.DoesNotExist:
            continue
        n = _create(
            recipient=manager,
            actor=actor or staff_member.user,
            message=f"Team member joined: {staff_name} joined as {job_role}.",
            link=link,
            notification_type="team_member_joined",
        )
        if n:
            created_notifs.append(n)
    return created_notifs


def notify_weekly_summary(*, recipient, active_projects=0, pending_tasks=0, actor=None):
    """
    Notify recipient of their weekly project & task recap.
    """
    link = reverse("dashboard")
    return _create(
        recipient=recipient,
        actor=actor,
        message=f"Weekly summary: You have {active_projects} active projects and {pending_tasks} pending tasks this week.",
        link=link,
        notification_type="weekly_summary",
    )


def check_and_notify_project_deadlines(user):
    """
    Check projects for the given user's organization and send deadline reminder / overdue alerts
    if the respective settings are enabled and notifications haven't already been sent today.
    """
    from django.utils import timezone
    from projects.models import Project
    from accounts.models import OrganizationMembership
    from .models import Notification

    membership = OrganizationMembership.objects.filter(user=user).first()
    if not membership or not membership.organization:
        return

    today = timezone.now().date()
    projects = Project.objects.filter(
        organization=membership.organization,
    ).exclude(status="COMPLETED")

    for project in projects:
        if not project.deadline:
            continue

        days_diff = (project.deadline - today).days

        # Overdue
        if days_diff < 0:
            already_notified = Notification.objects.filter(
                recipient=user,
                notification_type="overdue_alert",
                link__contains=f"/projects/{project.pk}/",
                created_at__date=today,
            ).exists()
            if not already_notified:
                notify_overdue_alert(recipient=user, project=project)

        # Approaching deadline (0 to 2 days)
        elif 0 <= days_diff <= 2:
            already_notified = Notification.objects.filter(
                recipient=user,
                notification_type="deadline_reminder",
                link__contains=f"/projects/{project.pk}/",
                created_at__date=today,
            ).exists()
            if not already_notified:
                notify_deadline_reminder(recipient=user, project=project, days_left=days_diff)


def notify_account_activity(*, recipient, message, link="/settings/?tab=profile", actor=None):
    """
    Notify recipient of login, logout, and profile picture updates.
    """
    return _create(
        recipient=recipient,
        actor=actor,
        message=message,
        link=link,
        notification_type="account_activity",
    )




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


def _create(*, recipient, actor, message, link=""):
    """
    Internal helper.  Imports Notification lazily to avoid circular
    imports at module load time (the model imports settings.AUTH_USER_MODEL).
    Swallows exceptions so a notification failure never breaks the primary action.
    """
    try:
        from .models import Notification
        Notification.objects.create(
            recipient=recipient,
            actor=actor,
            message=message,
            link=link,
        )
    except Exception as exc:
        logger.error("Failed to create notification for %s: %s", recipient, exc)


# ────────────────────────────────────────────────────────────────────────────
# Event A — Staff assigned to a project  (Phase 1 hook point)
# ────────────────────────────────────────────────────────────────────────────

def notify_staff_assigned_to_project(*, actor, staff_user, project):
    """
    Notify a Staff member that they have been assigned to a project.

    Called from projects/views.py :: assign_staff(), once per newly
    created StaffAssignment record.

    Parameters
    ──────────
    actor      : accounts.User  — the Manager who performed the assignment
    staff_user : accounts.User  — the Staff member receiving the notification
    project    : projects.Project
    """
    if staff_user is None:
        return
    link = reverse("projects:project_detail", kwargs={"pk": project.pk})
    _create(
        recipient=staff_user,
        actor=actor,
        message=f"You have been assigned to the project: {project.name}.",
        link=link,
    )


# ────────────────────────────────────────────────────────────────────────────
# Event B — Task assigned to Staff  (Phase 2 hook point)
# ────────────────────────────────────────────────────────────────────────────

def notify_task_assigned(*, actor, task):
    """
    Notify the assigned Staff member that a new task has been created for them.

    Called from projects/views.py :: task_create().

    Parameters
    ──────────
    actor : accounts.User  — the Manager who created/assigned the task
    task  : projects.Task
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
    )


# ────────────────────────────────────────────────────────────────────────────
# Event B (edit) — Task reassigned to a different Staff member
# ────────────────────────────────────────────────────────────────────────────

def notify_task_reassigned(*, actor, task, previous_user):
    """
    Notify the new assignee when a task is reassigned by a Manager.

    Called from projects/views.py :: task_edit() when assigned_to changes.

    Parameters
    ──────────
    actor         : accounts.User  — the Manager performing the reassignment
    task          : projects.Task  (already saved with new assigned_to)
    previous_user : accounts.User | None  — the previous assignee (not notified
                    in Phase 3 — a future phase can add that if desired)
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
    )


# ────────────────────────────────────────────────────────────────────────────
# Event C — Task status updated by Staff  (Phase 2 hook point)
# ────────────────────────────────────────────────────────────────────────────

def notify_task_status_updated(*, actor, task):
    """
    Notify the project's Manager(s) when a Staff member updates a task status.

    Called from projects/views.py :: task_status_update().

    We notify all Managers who have an active OrganizationMembership for the
    project's organization, rather than just project.created_by, because an
    organization may have multiple Managers.

    Parameters
    ──────────
    actor : accounts.User  — the Staff member who updated the status
    task  : projects.Task  (already saved with new status)
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
        )

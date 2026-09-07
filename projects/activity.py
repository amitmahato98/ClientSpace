"""
projects/activity.py
─────────────────────
Thin service layer for creating ProjectActivity records.

Centralising all activity writes here means:
  • Views stay readable — one-line calls with clear intent.
  • The exact description format is defined in one place.
  • Future phases (e.g. webhooks, exports) can tap this layer.

All functions are silent on failure — a logging error is recorded but
the exception is never re-raised, so an activity write failure never
breaks the primary action.

Usage
─────
    from projects.activity import log_project_created
    log_project_created(actor=request.user, project=project)
"""

import logging

logger = logging.getLogger(__name__)


def _log(*, project, actor, action_type, description):
    """Internal helper — imports lazily, swallows exceptions."""
    try:
        from .models import ProjectActivity
        ProjectActivity.objects.create(
            project=project,
            actor=actor,
            action_type=action_type,
            description=description,
        )
    except Exception as exc:
        logger.error(
            "Failed to create ProjectActivity [%s] for project %s: %s",
            action_type, getattr(project, "pk", "?"), exc,
        )


def _actor_name(actor):
    """Return the best display name for an actor user object."""
    if actor is None:
        return "Someone"
    full = actor.get_full_name().strip()
    return full if full else actor.username


# ─────────────────────────────────────────────────────────────────────────
# Trigger functions  (called from projects/views.py)
# ─────────────────────────────────────────────────────────────────────────

def log_project_created(*, actor, project):
    """Project creation event."""
    from .models import ProjectActivity
    _log(
        project=project,
        actor=actor,
        action_type=ProjectActivity.ActionType.PROJECT_CREATED,
        description=f"{_actor_name(actor)} created the project.",
    )


def log_staff_assigned(*, actor, project, staff_name):
    """A staff member was assigned to the project (Phase 1)."""
    from .models import ProjectActivity
    _log(
        project=project,
        actor=actor,
        action_type=ProjectActivity.ActionType.STAFF_ASSIGNED,
        description=f"{_actor_name(actor)} assigned {staff_name} to the project.",
    )


def log_staff_removed(*, actor, project, staff_name):
    """A staff member was removed from the project."""
    from .models import ProjectActivity
    _log(
        project=project,
        actor=actor,
        action_type=ProjectActivity.ActionType.STAFF_REMOVED,
        description=f"{_actor_name(actor)} removed {staff_name} from the project.",
    )


def log_task_added(*, actor, project, task):
    """A new task was created and (optionally) assigned (Phase 2)."""
    from .models import ProjectActivity
    assignee = task.assigned_display_name
    if task.assigned_to:
        desc = (
            f"{_actor_name(actor)} created task \"{task.title}\" "
            f"and assigned it to {assignee}."
        )
    else:
        desc = f"{_actor_name(actor)} created task \"{task.title}\"."
    _log(
        project=project,
        actor=actor,
        action_type=ProjectActivity.ActionType.TASK_ADDED,
        description=desc,
    )


def log_task_updated(*, actor, project, task):
    """A task's details were edited by a Manager."""
    from .models import ProjectActivity
    _log(
        project=project,
        actor=actor,
        action_type=ProjectActivity.ActionType.TASK_UPDATED,
        description=f"{_actor_name(actor)} updated task \"{task.title}\".",
    )


def log_task_status(*, actor, project, task):
    """A staff member changed a task's status."""
    from .models import ProjectActivity
    _log(
        project=project,
        actor=actor,
        action_type=ProjectActivity.ActionType.TASK_STATUS,
        description=(
            f"{_actor_name(actor)} moved \"{task.title}\" "
            f"to {task.get_status_display()}."
        ),
    )


def log_task_deleted(*, actor, project, task_title):
    """A task was deleted by a Manager."""
    from .models import ProjectActivity
    _log(
        project=project,
        actor=actor,
        action_type=ProjectActivity.ActionType.TASK_DELETED,
        description=f"{_actor_name(actor)} deleted task \"{task_title}\".",
    )

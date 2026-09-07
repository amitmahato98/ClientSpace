from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count
from django.shortcuts import render
from django.utils import timezone

from accounts.decorators import staff_or_above
from projects.models import Project, Task, ProjectActivity


@staff_or_above
def dashboard(request):
    """
    Main dashboard — accessible to MANAGER and STAFF only.
    CLIENT users are blocked at the middleware level (Stage 3) and also here
    by the @staff_or_above decorator as a second line of defence.

    Phase 5: Calculate real metrics from database.
    """
    user = request.user
    now = timezone.now()

    # ── Projects metrics ──────────────────────────────────────────
    # Active projects (not completed)
    active_projects_count = Project.objects.exclude(
        status=Project.Status.COMPLETED
    ).count()

    # Overdue projects (deadline passed, not completed)
    overdue_projects_count = Project.objects.filter(
        deadline__lt=now.date(),
    ).exclude(
        status=Project.Status.COMPLETED
    ).count()

    # Due this week (deadline within next 7 days, not completed)
    week_end = now.date() + timezone.timedelta(days=7)
    due_this_week_count = Project.objects.filter(
        deadline__gte=now.date(),
        deadline__lte=week_end,
    ).exclude(
        status=Project.Status.COMPLETED
    ).count()

    # ── Tasks metrics ─────────────────────────────────────────────
    if user.is_staff_member:
        # Staff: only tasks assigned to them
        my_tasks_count = Task.objects.filter(assigned_to=user).count()
        
        tasks_due_soon_count = Task.objects.filter(
            assigned_to=user,
            due_date__gte=now.date(),
            due_date__lte=week_end,
        ).exclude(
            status=Task.Status.COMPLETED
        ).count()
    else:
        # Manager: all tasks
        my_tasks_count = Task.objects.count()
        
        tasks_due_soon_count = Task.objects.filter(
            due_date__gte=now.date(),
            due_date__lte=week_end,
        ).exclude(
            status=Task.Status.COMPLETED
        ).count()

    # ── Recent projects ───────────────────────────────────────────
    recent_projects = (
        Project.objects
        .select_related("client", "created_by")
        .prefetch_related("tasks")
        .exclude(status=Project.Status.COMPLETED)
        .order_by("-created_at")[:4]
    )

    # Annotate with task counts
    projects_with_stats = []
    for project in recent_projects:
        total_tasks = project.tasks.count()
        completed_tasks = project.tasks.filter(status=Task.Status.COMPLETED).count()
        progress = int((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 0
        
        projects_with_stats.append({
            "project": project,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "progress": progress,
        })

    # ── Recent activity ───────────────────────────────────────────
    recent_activity = (
        ProjectActivity.objects
        .select_related("project", "actor")
        .order_by("-created_at")[:6]
    )

    # ── Staff count ───────────────────────────────────────────────
    from accounts.models import User
    staff_count = User.objects.filter(role=User.Role.STAFF).count()

    return render(request, 'dashboard/dashboard.html', {
        "active_projects_count": active_projects_count,
        "overdue_projects_count": overdue_projects_count,
        "due_this_week_count": due_this_week_count,
        "my_tasks_count": my_tasks_count,
        "tasks_due_soon_count": tasks_due_soon_count,
        "staff_count": staff_count,
        "recent_projects": projects_with_stats,
        "recent_activity": recent_activity,
    })

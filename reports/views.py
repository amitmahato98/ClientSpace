"""
reports/views.py
────────────────
Progress & Reports section of the Manager portal.

No new database tables are needed — every number is derived from the
existing Project, Task, ProjectActivity, StaffAssignment and Payment models.

Progress rules
──────────────
• A task's effective progress is 100 % when its status is COMPLETED,
  otherwise the staff-reported `completion_percent`.  (completion_percent
  is independent of status in this codebase, so a COMPLETED task can still
  hold 0 in that column — we must not average the raw column.)
• A project's progress is the mean of its tasks' effective progress.
  A project with no tasks shows 0 % (100 % if the project is COMPLETED).

Security
────────
• Manager-only (@manager_required) and scoped to the manager's organisation
  — the same pattern used by projects.views.task_overview.
"""

import csv
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import manager_required
from accounts.views import get_user_organization
from clients.models import Payment
from projects.models import Project, ProjectActivity, Task

# ──────────────────────────────────────────────────────────────────────────
# Presentation constants
# ──────────────────────────────────────────────────────────────────────────

# key -> (label, badge background, badge text colour)
HEALTH = {
    "completed":   ("Completed",        "#e6f4ea", "#137333"),
    "overdue":     ("Overdue",          "#fce8e6", "#c5221f"),
    "blocked":     ("Blocked",          "#fce8e6", "#c5221f"),
    "at_risk":     ("At Risk",          "#fef7e0", "#b06000"),
    "behind":      ("Behind Schedule",  "#fef7e0", "#b06000"),
    "on_hold":     ("On Hold",          "#f3f4f6", "#6b7280"),
    "on_track":    ("On Track",         "#e6f4ea", "#137333"),
}

PROJECT_STATUS_COLORS = {
    Project.Status.PLANNING:    "#1a73e8",
    Project.Status.IN_PROGRESS: "#137333",
    Project.Status.AT_RISK:     "#b06000",
    Project.Status.BLOCKED:     "#c5221f",
    Project.Status.COMPLETED:   "#8ab4a0",
    Project.Status.ON_HOLD:     "#9ca3af",
}

TASK_STATUS_COLORS = {
    Task.Status.PENDING:     "#c9c2b6",
    Task.Status.IN_PROGRESS: "#1a73e8",
    Task.Status.COMPLETED:   "#137333",
}

BEHIND_TOLERANCE = 20  # percentage points below the time-elapsed expectation


# ──────────────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────────────

def _task_percent(task):
    """Effective progress of a single task (see module docstring)."""
    return 100 if task.status == Task.Status.COMPLETED else task.completion_percent


def _task_is_overdue(task, today):
    return bool(
        task.due_date
        and task.due_date < today
        and task.status != Task.Status.COMPLETED
    )


def _bar_color(percent):
    if percent >= 100:
        return "#137333"
    if percent >= 60:
        return "#d4a373"
    if percent >= 30:
        return "#e0a84a"
    return "#e0532e"


def _expected_percent(project, today):
    """How far through its timeline the project is (None if dates missing)."""
    if not project.start_date or not project.deadline:
        return None
    total = (project.deadline - project.start_date).days
    if total <= 0:
        return 100 if today >= project.deadline else 0
    elapsed = (today - project.start_date).days
    return max(0, min(100, round(elapsed / total * 100)))


def _deadline_note(project, today):
    if not project.deadline:
        return "No deadline", False
    delta = (project.deadline - today).days
    if project.status == Project.Status.COMPLETED:
        return "Delivered", False
    if delta < 0:
        n = abs(delta)
        return f"{n} day{'s' if n != 1 else ''} overdue", True
    if delta == 0:
        return "Due today", False
    return f"{delta} day{'s' if delta != 1 else ''} left", False


def _health_key(project, progress, expected, overdue):
    if project.status == Project.Status.COMPLETED:
        return "completed"
    if overdue:
        return "overdue"
    if project.status == Project.Status.BLOCKED:
        return "blocked"
    if project.status == Project.Status.AT_RISK:
        return "at_risk"
    if project.status == Project.Status.ON_HOLD:
        return "on_hold"
    if expected is not None and progress < expected - BEHIND_TOLERANCE:
        return "behind"
    return "on_track"


def _conic(segments):
    """Build a CSS conic-gradient from [(value, colour), …] for donut charts."""
    total = sum(v for v, _ in segments)
    if not total:
        return "conic-gradient(#f2ede4 0 100%)"
    stops, acc = [], 0
    for value, colour in segments:
        if not value:
            continue
        start = acc / total * 100
        acc += value
        end = acc / total * 100
        stops.append(f"{colour} {start:.2f}% {end:.2f}%")
    return "conic-gradient(" + ", ".join(stops) + ")"


def _csv_safe(value):
    """Neutralise spreadsheet formula injection in exported text cells."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def _payment_totals(project_ids):
    """{project_id: {'paid': Decimal, 'pending': Decimal}} in two queries."""
    totals = defaultdict(lambda: {"paid": Decimal("0"), "pending": Decimal("0")})
    rows = (
        Payment.objects
        .filter(project_id__in=project_ids, status__in=["paid", "pending"])
        .values("project_id", "status")
        .annotate(total=Sum("amount"))
    )
    for row in rows:
        key = "paid" if row["status"] == "paid" else "pending"
        totals[row["project_id"]][key] = row["total"] or Decimal("0")
    return totals


def _build_project_metrics(project, tasks, today, pay):
    """Everything the templates need to describe one project."""
    total = len(tasks)
    done = sum(1 for t in tasks if t.status == Task.Status.COMPLETED)
    in_progress = sum(1 for t in tasks if t.status == Task.Status.IN_PROGRESS)
    pending = total - done - in_progress
    overdue_tasks = sum(1 for t in tasks if _task_is_overdue(t, today))

    if total:
        progress = round(sum(_task_percent(t) for t in tasks) / total)
    else:
        progress = 100 if project.status == Project.Status.COMPLETED else 0

    expected = _expected_percent(project, today)
    note, deadline_overdue = _deadline_note(project, today)
    overdue = deadline_overdue and project.status != Project.Status.COMPLETED
    key = _health_key(project, progress, expected, overdue)
    label, bg, fg = HEALTH[key]

    budget = project.budget or Decimal("0")
    paid = pay["paid"]
    paid_pct = min(100, round(paid / budget * 100)) if budget > 0 else 0

    return {
        "project": project,
        "total": total,
        "done": done,
        "in_progress": in_progress,
        "pending": pending,
        "overdue_tasks": overdue_tasks,
        "progress": progress,
        "bar_color": _bar_color(progress),
        "expected": expected,
        "health_key": key,
        "health_label": label,
        "health_bg": bg,
        "health_fg": fg,
        "deadline_note": note,
        "deadline_overdue": overdue,
        "budget": budget,
        "paid": paid,
        "pending_pay": pay["pending"],
        "paid_pct": paid_pct,
        "outstanding": max(budget - paid, Decimal("0")),
    }


def _staff_workload(tasks, today):
    """Per-staff rollup used by the workload table."""
    buckets = defaultdict(list)
    for t in tasks:
        buckets[t.assigned_to_id].append(t)

    rows = []
    for _, items in buckets.items():
        owner = items[0].assigned_to
        total = len(items)
        done = sum(1 for t in items if t.status == Task.Status.COMPLETED)
        rows.append({
            "name": owner.get_full_name().strip() or owner.username if owner else "Unassigned",
            "initials": owner.initials if owner else "?",
            "total": total,
            "done": done,
            "in_progress": sum(1 for t in items if t.status == Task.Status.IN_PROGRESS),
            "overdue": sum(1 for t in items if _task_is_overdue(t, today)),
            "avg": round(sum(_task_percent(t) for t in items) / total),
            "projects": len({t.project_id for t in items}),
        })
    rows.sort(key=lambda r: (-r["total"], r["name"].lower()))
    for r in rows:
        r["bar_color"] = _bar_color(r["avg"])
    return rows


def _task_row(task, today):
    return {
        "task": task,
        "percent": _task_percent(task),
        "overdue": _task_is_overdue(task, today),
        "days": (task.due_date - today).days if task.due_date else None,
    }


# ──────────────────────────────────────────────────────────────────────────
# Shared data loader (overview page + CSV export use the same filters)
# ──────────────────────────────────────────────────────────────────────────

def _load_report_data(request, org):
    today = timezone.localdate()

    f_status = request.GET.get("status", "")
    f_health = request.GET.get("health", "")
    f_q = request.GET.get("q", "").strip()

    projects = (
        Project.objects
        .filter(organization=org)
        .select_related("client")
    )
    if f_status in Project.Status.values:
        projects = projects.filter(status=f_status)
    if f_q:
        from django.db.models import Q
        projects = projects.filter(
            Q(name__icontains=f_q)
            | Q(client__username__icontains=f_q)
            | Q(client__first_name__icontains=f_q)
            | Q(client__last_name__icontains=f_q)
        )
    projects = list(projects.order_by("-created_at"))
    project_ids = [p.pk for p in projects]

    all_tasks = list(
        Task.objects
        .filter(project_id__in=project_ids)
        .select_related("project", "assigned_to")
        .order_by("due_date", "title")
    )
    tasks_by_project = defaultdict(list)
    for t in all_tasks:
        tasks_by_project[t.project_id].append(t)

    pay = _payment_totals(project_ids)

    rows = [
        _build_project_metrics(p, tasks_by_project[p.pk], today, pay[p.pk])
        for p in projects
    ]
    if f_health in HEALTH:
        rows = [r for r in rows if r["health_key"] == f_health]
        keep = {r["project"].pk for r in rows}
        all_tasks = [t for t in all_tasks if t.project_id in keep]

    return today, rows, all_tasks, {"status": f_status, "health": f_health, "q": f_q}


# ══════════════════════════════════════════════════════════════════════════
# OVERVIEW
# ══════════════════════════════════════════════════════════════════════════

@manager_required
def reports_overview(request):
    org = get_user_organization(request.user)
    if org is None:
        messages.error(request, "You must belong to an organisation to view reports.")
        return redirect("projects:project_list")

    today, rows, tasks, filters = _load_report_data(request, org)

    # ── KPIs ────────────────────────────────────────────────────────────
    total_projects = len(rows)
    completed_projects = sum(1 for r in rows if r["health_key"] == "completed")
    attention = sum(
        1 for r in rows
        if r["health_key"] in ("overdue", "blocked", "at_risk", "behind")
    )
    total_tasks = len(tasks)
    done_tasks = sum(1 for t in tasks if t.status == Task.Status.COMPLETED)
    in_progress_tasks = sum(1 for t in tasks if t.status == Task.Status.IN_PROGRESS)
    pending_tasks = total_tasks - done_tasks - in_progress_tasks
    overdue_tasks = sum(1 for t in tasks if _task_is_overdue(t, today))

    overall_progress = (
        round(sum(_task_percent(t) for t in tasks) / total_tasks) if total_tasks else 0
    )
    completion_rate = round(done_tasks / total_tasks * 100) if total_tasks else 0

    total_budget = sum((r["budget"] for r in rows), Decimal("0"))
    total_paid = sum((r["paid"] for r in rows), Decimal("0"))
    total_pending_pay = sum((r["pending_pay"] for r in rows), Decimal("0"))
    collected_pct = round(total_paid / total_budget * 100) if total_budget > 0 else 0

    # ── Chart data ──────────────────────────────────────────────────────
    task_segments = [
        (done_tasks, TASK_STATUS_COLORS[Task.Status.COMPLETED]),
        (in_progress_tasks, TASK_STATUS_COLORS[Task.Status.IN_PROGRESS]),
        (pending_tasks, TASK_STATUS_COLORS[Task.Status.PENDING]),
    ]
    task_legend = [
        {"label": "Completed",   "count": done_tasks,        "color": TASK_STATUS_COLORS[Task.Status.COMPLETED]},
        {"label": "In Progress", "count": in_progress_tasks, "color": TASK_STATUS_COLORS[Task.Status.IN_PROGRESS]},
        {"label": "Pending",     "count": pending_tasks,     "color": TASK_STATUS_COLORS[Task.Status.PENDING]},
    ]

    status_counts = defaultdict(int)
    for r in rows:
        status_counts[r["project"].status] += 1
    project_status_bars = [
        {
            "label": label,
            "count": status_counts[value],
            "color": PROJECT_STATUS_COLORS[value],
            "pct": round(status_counts[value] / total_projects * 100) if total_projects else 0,
        }
        for value, label in Project.Status.choices
    ]

    # ── Attention lists ─────────────────────────────────────────────────
    horizon = today + timedelta(days=14)
    overdue_list = [
        _task_row(t, today) for t in tasks if _task_is_overdue(t, today)
    ][:8]
    upcoming_list = [
        _task_row(t, today) for t in tasks
        if t.due_date and today <= t.due_date <= horizon
        and t.status != Task.Status.COMPLETED
    ][:8]

    activities = (
        ProjectActivity.objects
        .filter(project_id__in=[r["project"].pk for r in rows])
        .select_related("project", "actor")
        .order_by("-created_at")[:8]
    )

    return render(request, "reports/reports.html", {
        "today": today,
        "rows": rows,
        "filters": filters,
        "status_choices": Project.Status.choices,
        "health_choices": [(k, v[0]) for k, v in HEALTH.items()],

        "total_projects": total_projects,
        "completed_projects": completed_projects,
        "attention": attention,
        "total_tasks": total_tasks,
        "done_tasks": done_tasks,
        "overdue_tasks": overdue_tasks,
        "overall_progress": overall_progress,
        "overall_color": _bar_color(overall_progress),
        "completion_rate": completion_rate,

        "total_budget": total_budget,
        "total_paid": total_paid,
        "total_pending_pay": total_pending_pay,
        "collected_pct": collected_pct,

        "task_donut": _conic(task_segments),
        "task_legend": task_legend,
        "project_status_bars": project_status_bars,

        "workload": _staff_workload([t for t in tasks if t.assigned_to_id], today),
        "unassigned_count": sum(1 for t in tasks if not t.assigned_to_id),
        "overdue_list": overdue_list,
        "upcoming_list": upcoming_list,
        "activities": activities,
    })


# ══════════════════════════════════════════════════════════════════════════
# SINGLE-PROJECT REPORT
# ══════════════════════════════════════════════════════════════════════════

@manager_required
def project_report(request, pk):
    from staff.models import StaffAssignment

    org = get_user_organization(request.user)
    if org is None:
        messages.error(request, "You must belong to an organisation to view reports.")
        return redirect("projects:project_list")

    project = get_object_or_404(
        Project.objects.select_related("client", "created_by"),
        pk=pk, organization=org,
    )
    today = timezone.localdate()

    tasks = list(
        Task.objects
        .filter(project=project)
        .select_related("assigned_to")
        .order_by("due_date", "title")
    )
    payments = list(Payment.objects.filter(project=project).order_by("-date"))
    pay = _payment_totals([project.pk])[project.pk]
    m = _build_project_metrics(project, tasks, today, pay)

    task_rows = [_task_row(t, today) for t in tasks]
    status_filter = request.GET.get("status", "")
    if status_filter in Task.Status.values:
        task_rows = [r for r in task_rows if r["task"].status == status_filter]

    priority_counts = [
        {
            "label": label,
            "count": sum(1 for t in tasks if t.priority == value),
            "done": sum(1 for t in tasks if t.priority == value and t.status == Task.Status.COMPLETED),
        }
        for value, label in Task.Priority.choices
    ]

    team = (
        StaffAssignment.objects
        .filter(project=project, is_active=True)
        .select_related("staff")
        .order_by("assigned_at")
    )

    # Timeline (days)
    timeline = None
    if project.start_date and project.deadline:
        span = max((project.deadline - project.start_date).days, 0)
        elapsed = max(min((today - project.start_date).days, span), 0) if span else 0
        timeline = {"span": span, "elapsed": elapsed}

    return render(request, "reports/project_report.html", {
        "m": m,
        "project": project,
        "today": today,
        "task_rows": task_rows,
        "status_filter": status_filter,
        "task_donut": _conic([
            (m["done"], TASK_STATUS_COLORS[Task.Status.COMPLETED]),
            (m["in_progress"], TASK_STATUS_COLORS[Task.Status.IN_PROGRESS]),
            (m["pending"], TASK_STATUS_COLORS[Task.Status.PENDING]),
        ]),
        "priority_counts": priority_counts,
        "workload": _staff_workload([t for t in tasks if t.assigned_to_id], today),
        "team": team,
        "timeline": timeline,
        "payments": payments,
        "activities": (
            ProjectActivity.objects.filter(project=project)
            .select_related("actor").order_by("-created_at")[:12]
        ),
    })


# ══════════════════════════════════════════════════════════════════════════
# CSV EXPORT
# ══════════════════════════════════════════════════════════════════════════

@manager_required
def export_csv(request):
    org = get_user_organization(request.user)
    if org is None:
        return redirect("projects:project_list")

    today, rows, tasks, _ = _load_report_data(request, org)
    kind = request.GET.get("type", "projects")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="clientspace-{kind}-report-{today.isoformat()}.csv"'
    )
    response.write("\ufeff")  # BOM so Excel opens UTF-8 correctly
    w = csv.writer(response)

    if kind == "tasks":
        w.writerow(["Project", "Task", "Assigned To", "Status", "Priority",
                    "Completion %", "Due Date", "Overdue"])
        keep = {r["project"].pk for r in rows}
        for t in tasks:
            if t.project_id not in keep:
                continue
            w.writerow([
                _csv_safe(t.project.name), _csv_safe(t.title),
                _csv_safe(t.assigned_display_name), t.get_status_display(),
                t.get_priority_display(), _task_percent(t),
                t.due_date.isoformat() if t.due_date else "",
                "Yes" if _task_is_overdue(t, today) else "No",
            ])
    else:
        w.writerow(["Project", "Client", "Status", "Health", "Priority",
                    "Progress %", "Tasks Done", "Tasks Total", "Overdue Tasks",
                    "Start Date", "Deadline", "Budget (NPR)", "Paid (NPR)",
                    "Pending Payments (NPR)"])
        for r in rows:
            p = r["project"]
            w.writerow([
                _csv_safe(p.name), _csv_safe(p.client_display_name),
                p.get_status_display(), r["health_label"], p.get_priority_display(),
                r["progress"], r["done"], r["total"], r["overdue_tasks"],
                p.start_date.isoformat() if p.start_date else "",
                p.deadline.isoformat() if p.deadline else "",
                r["budget"], r["paid"], r["pending_pay"],
            ])
    return response

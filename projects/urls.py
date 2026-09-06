from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    # ── Project CRUD ────────────────────────────────────────────────────────
    path("",        views.project_list,   name="project_list"),
    path("create/", views.project_create, name="project_create"),
    path("<int:pk>/", views.project_detail, name="project_detail"),

    # ── Phase 1: Staff assignment ────────────────────────────────────────────
    path("<int:pk>/assign-staff/",                       views.assign_staff, name="assign_staff"),
    path("<int:pk>/remove-staff/<int:assignment_id>/",   views.remove_staff, name="remove_staff"),

    # ── Phase 2: Task management (Manager) ──────────────────────────────────
    path("<int:pk>/tasks/create/",                       views.task_create,  name="task_create"),
    path("<int:pk>/tasks/<int:task_id>/edit/",           views.task_edit,    name="task_edit"),
    path("<int:pk>/tasks/<int:task_id>/delete/",         views.task_delete,  name="task_delete"),

    # ── Phase 2: Task views (Staff) ──────────────────────────────────────────
    # Note: these have no project-pk prefix — they are user-scoped, not
    # project-scoped, so they sit at the /projects/tasks/... level.
    path("tasks/my/",                  views.my_tasks,            name="my_tasks"),
    path("tasks/<int:task_id>/status/", views.task_status_update,  name="task_status_update"),
]

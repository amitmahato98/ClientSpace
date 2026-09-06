from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    # /projects/
    path(
        "",
        views.project_list,
        name="project_list",
    ),

    # /projects/create/
    path(
        "create/",
        views.project_create,
        name="project_create",
    ),

    # /projects/<pk>/
    path(
        "<int:pk>/",
        views.project_detail,
        name="project_detail",
    ),

    # /projects/<pk>/assign-staff/   — MANAGER POST only
    path(
        "<int:pk>/assign-staff/",
        views.assign_staff,
        name="assign_staff",
    ),

    # /projects/<pk>/remove-staff/<assignment_id>/   — MANAGER POST only
    path(
        "<int:pk>/remove-staff/<int:assignment_id>/",
        views.remove_staff,
        name="remove_staff",
    ),
]

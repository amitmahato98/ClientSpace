from django.urls import path
from staff import views

urlpatterns = [
    path("staff/", views.staff, name="staff"),

    path(
        "add_staff/",
        views.add_staff,
        name="add_staff"
    ),

    path(
        "setup/<token>/",
        views.staff_setup,
        name="staff_setup"
    ),
    path(
    "assign-work/",
    views.assign_work,
    name="assign_work"
),

path(
    "staff/<int:staff_id>/view/",
    views.staff_view,
    name="staff_view"
),

path(
    "staff/<int:staff_id>/manage/",
    views.staff_manage,
    name="staff_manage"
),
path(
    "staff/<int:staff_id>/terminate/",
    views.terminate_project,
    name="terminate_project"
),

path(
    "staff/<int:staff_id>/delete/",
    views.delete_staff,
    name="delete_staff"
),
]
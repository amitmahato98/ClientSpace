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
]

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import manager_required
from .forms import ProjectForm
from .models import Project


# =========================================================
# PROJECT LIST
# =========================================================

@login_required
def project_list(request):
    """
    Show all projects.

    All authenticated users (MANAGER, STAFF, CLIENT) can view the list.
    The template hides the "New project" button for non-managers.
    """
    projects = Project.objects.select_related("client", "created_by").all()

    return render(request, "projects/projects.html", {
        "projects": projects,
    })


# =========================================================
# PROJECT CREATE  — MANAGER ONLY
# =========================================================

@manager_required
def project_create(request):
    """
    GET  → display the blank project creation form.
    POST → validate, save with created_by=request.user, redirect.

    The @manager_required decorator (from accounts.decorators) renders
    403.html for STAFF and CLIENT, so they can never create a project
    even by directly visiting /projects/create/.
    """
    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            # created_by is always set server-side — never from POST data.
            project.created_by = request.user
            project.save()
            messages.success(request, f'Project "{project.name}" created successfully.')
            return redirect("projects:project_list")
    else:
        form = ProjectForm()

    return render(request, "projects/project_form.html", {"form": form})


# =========================================================
# PROJECT DETAIL
# =========================================================

@login_required
def project_detail(request, pk):
    """
    Display details for a single project loaded from the database.

    Uses get_object_or_404 so a missing PK returns a clean 404 rather
    than a server error.
    """
    project = get_object_or_404(
        Project.objects.select_related("client", "created_by"),
        pk=pk,
    )

    return render(request, "projects/projectdetails.html", {
        "project": project,
    })

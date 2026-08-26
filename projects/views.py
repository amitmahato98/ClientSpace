from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.decorators import manager_required, staff_or_above


@login_required
def project_view(request):
    """
    Project list page.
    All authenticated roles can see the project list.
    Fine-grained object-level filtering (e.g. CLIENT sees only their projects)
    will be applied here once the Project model is defined.
    """
    return render(request, "projects/projects.html")


# ── Stubs for future Manager-only operations ──────────────────────────────────
# Uncomment and flesh out as the Project model is built out.

# @manager_required
# def project_create(request):
#     ...

# @manager_required
# def project_delete(request, pk):
#     ...

# @staff_or_above
# def project_update(request, pk):
#     ...

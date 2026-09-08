from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from projects.models import Project

from accounts.models import OrganizationMembership

from accounts.decorators import staff_or_above

from django.db.models import Sum


@staff_or_above
def dashboard(request):
    """
    Main dashboard — accessible to MANAGER and STAFF only.
    CLIENT users are blocked at the middleware level (Stage 3) and also here
    by the @staff_or_above decorator as a second line of defence.
    """

    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).first()

    if not membership:
        return render(
            request,
            "dashboard/dashboard.html"
        )

    organization = membership.organization

    active_projects = Project.objects.filter(
        organization=organization
    ).exclude(
        status=Project.Status.COMPLETED
    )

    active_project_count = active_projects.count()

    client_count = active_projects.values(
        "client"
    ).distinct().count()

    budget_sum=Project.objects.aggregate(total=Sum('budget'))['total']

    return render(
        request,
        "dashboard/dashboard.html",
        {
            "active_project_count": active_project_count,
            "client_count": client_count,
            "budget_sum":budget_sum,
        }
    )

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from accounts.decorators import staff_or_above
from accounts.models import OrganizationMembership
from accounts.views import get_user_organization
from projects.models import Project

User = get_user_model()


@login_required
@staff_or_above
def clients_page(request):
    """
    Client list page.

    A "Client" is a User with role=CLIENT who belongs (via
    OrganizationMembership) to the logged-in Manager/Staff member's
    organization. There is no separate Client table anymore — this view
    reads directly from accounts.User + projects.Project.
    """
    org = get_user_organization(request.user)

    if org is None:
        messages.error(
            request,
            "You must set up your organisation before viewing clients. "
            "Please complete the onboarding step first.",
        )
        return redirect(reverse("accounts:create_organization"))

    client_ids = OrganizationMembership.objects.filter(
        organization=org,
        role=OrganizationMembership.Role.CLIENT,
    ).values_list('user_id', flat=True)

    clients = User.objects.filter(id__in=client_ids).order_by('username')
    selected = clients.first()

    client_id = request.GET.get('client')
    if client_id:
        selected = get_object_or_404(clients, id=client_id)

    financials = None
    if selected:
        total_billed = (
            Project.objects.filter(client=selected)
            .aggregate(total=Sum('budget'))['total'] or 0
        )
        total_paid = (
            selected.payments.filter(status='paid')
            .aggregate(total=Sum('amount'))['total'] or 0
        )
        financials = {
            'total_billed': total_billed,
            'total_paid': total_paid,
            'outstanding': total_billed - total_paid,
        }

    return render(request, 'clients/clients.html', {
        'clients': clients,
        'selected': selected,
        'financials': financials,
    })
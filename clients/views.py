from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.decorators import manager_required, staff_or_above


@login_required
def clients_page(request):
    """
    Client list page.
    MANAGER and STAFF can see all clients.
    CLIENT users will only see their own profile once the model is in place.
    """
    return render(request, "clients/clients.html")


# ── Stubs for future Manager-only operations ──────────────────────────────────

# @manager_required
# def client_create(request):
#     ...

# @manager_required
# def client_delete(request, pk):
#     ...

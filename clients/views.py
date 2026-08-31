from django.shortcuts import render, get_object_or_404

from accounts.decorators import staff_or_above

from .models import Client


@staff_or_above
def clients_page(request):
    """
    Client list page.
    MANAGER and STAFF can see all clients.
    CLIENT users are blocked by middleware Stage 3 and by this decorator.
    """
    clients = Client.objects.all()
    selected = clients.first()

    client_id = request.GET.get('client')
    if client_id:
        selected = get_object_or_404(Client, id=client_id)

    return render(request, 'clients/clients.html', {
        'clients': clients,
        'selected': selected,
    })


# ── Stubs for future Manager-only operations ──────────────────────────────────

# @manager_required
# def client_create(request):
#     ...

# @manager_required
# def client_delete(request, pk):
#     ...
from django.shortcuts import render, get_object_or_404
from .models import Client

def clients_page(request):
    clients = Client.objects.all()
    selected = clients.first()

    client_id = request.GET.get('client')
    if client_id:
        selected = get_object_or_404(Client, id=client_id)

    return render(request, 'clients/clients.html', {
        'clients': clients,
        'selected': selected,
    })
from django.shortcuts import render

def clients_page(request):
    return render(request, 'clients/clients.html')
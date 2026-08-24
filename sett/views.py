from django.shortcuts import render

# Create your views here.


def settings_page(request):
    return render(request, 'settings.html')
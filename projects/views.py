from django.shortcuts import render

# Create your views here.
def project_view(request):
    return render(request, 'projects/projects.html')
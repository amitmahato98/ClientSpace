from django.shortcuts import render

def staff(request):
    return render(request,"staff/staff.html")


def add_staff(request):
    return render(request, 'satff/add_staff.html')

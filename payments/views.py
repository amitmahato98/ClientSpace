from django.shortcuts import render

# Create your views here.

def payment_view(request):
    return render(request, 'payments/payment.html')
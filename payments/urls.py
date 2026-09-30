from django.urls import path
from payments import views

app_name = "payments"

urlpatterns = [
    path(" ", views.payment_view, name="payment_view"),
]
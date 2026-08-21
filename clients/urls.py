from django.urls import path
from . import views

urlpatterns = [
    path('', views.clients_page, name='clients'),
]
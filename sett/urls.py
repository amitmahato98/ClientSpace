from django.urls import path
from . import views

app_name = "sett"

urlpatterns = [
    path("", views.settings_page, name="settings"),
]
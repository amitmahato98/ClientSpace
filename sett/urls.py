from django.urls import path
from . import views

app_name = "sett"

urlpatterns = [
    path("", views.settings_page, name="settings"),
    path("ajax/toggle-notification/", views.toggle_notification_setting_ajax, name="ajax_toggle_notification"),
]
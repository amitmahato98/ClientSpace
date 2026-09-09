from django.urls import path

from . import views


app_name = "helpcenter"

urlpatterns = [
    path("", views.help_home, name="home"),
    path("contact/", views.contact_submit, name="contact"),

]

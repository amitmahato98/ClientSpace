from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register, name="register"),
    path("google/", views.google_login, name="google_login"),
    path(
        "forgot-password/",
        auth_views.PasswordResetView.as_view(
            template_name="login_register/forgot_password.html",
            email_template_name="login_register/password_reset_email.html",
            success_url="/forgot-password/done/",
        ),
        name="password_reset",
    ),
    path(
        "forgot-password/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="login_register/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="login_register/password_reset_confirm.html",
            success_url="/reset/done/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="login_register/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]
from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    # ── Authentication ───────────────────────────────────────────────────────
    path("login/",   views.login_view,   name="login"),
    path("logout/",  views.logout_view,  name="logout"),

    # ── Registration ─────────────────────────────────────────────────────────
    path("register/",     views.register_view,     name="register"),
    path("register/otp/", views.register_otp_view, name="register_otp"),

    # ── Organization onboarding (post-registration) ──────────────────────────
    path("create-organization/", views.create_organization_view, name="create_organization"),

    # ── Password reset (OTP-based) ────────────────────────────────────────────
    path("forgot-password/",       views.forgot_password_view,     name="forgot_password"),
    path("forgot-password/otp/",   views.forgot_password_otp_view, name="forgot_password_otp"),
    path("forgot-password/reset/", views.set_new_password_view,    name="set_new_password"),

    # ── Google OAuth placeholder ─────────────────────────────────────────────
    path("google/", views.google_login, name="google_login"),

    # ── Dashboard (authenticated landing) ────────────────────────────────────
    path("dashboard/", views.dashboard_view, name="dashboard"),
]

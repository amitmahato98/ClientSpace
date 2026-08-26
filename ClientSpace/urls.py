from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, include


def home_view(request):
    """
    Root URL dispatcher.

    Anonymous            → /login/
    Authenticated, no org → /create-organization/
    Authenticated, has org → /dashboard/
    """
    if not request.user.is_authenticated:
        return redirect("accounts:login")

    from accounts.models import OrganizationMembership

    if not OrganizationMembership.objects.filter(user=request.user).exists():
        return redirect("accounts:create_organization")

    return redirect("accounts:dashboard")


urlpatterns = [
    path("admin/", admin.site.urls),

    # Authentication, registration, OTP, organization onboarding, dashboard
    path("", include("accounts.urls", namespace="accounts")),

    # Protected application areas
    path("projects/", include("projects.urls")),
    path("clients/", include("clients.urls")),
    path("settings/", include("sett.urls")),

    # Dashboard application added in main
    path("dashboard/", include("dashboard.urls")),

    # Root URL — smart redirect based on authentication + organization state
    path("", home_view, name="home"),
]

# Serve uploaded media files during development.
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
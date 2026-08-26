import re

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


# ─────────────────────────────────────────────────────────────────────────────
# URLs anonymous users may visit without authentication.
# ─────────────────────────────────────────────────────────────────────────────
PUBLIC_URL_PATTERNS = [
    r"^/login/$",
    r"^/register/$",
    r"^/register/otp/$",
    r"^/forgot-password/$",
    r"^/forgot-password/otp/$",
    r"^/forgot-password/reset/$",
    r"^/google/$",
    r"^/admin/",
    r"^/static/",
    r"^/media/",
    r"^/favicon\.ico$",
]

# ─────────────────────────────────────────────────────────────────────────────
# URLs authenticated-but-not-yet-onboarded users may visit.
# This set must include the onboarding page itself plus all auth/public URLs,
# otherwise a redirect loop forms when the onboarding page tries to load.
# ─────────────────────────────────────────────────────────────────────────────
ONBOARDING_EXEMPT_PATTERNS = PUBLIC_URL_PATTERNS + [
    r"^/create-organization/$",
    r"^/logout/$",
]

_PUBLIC_RE = re.compile("|".join(f"(?:{p})" for p in PUBLIC_URL_PATTERNS))
_ONBOARDING_EXEMPT_RE = re.compile(
    "|".join(f"(?:{p})" for p in ONBOARDING_EXEMPT_PATTERNS)
)


class LoginRequiredMiddleware:
    """
    Two-stage access gate that runs on every request.

    Stage 1 — Authentication gate
    ──────────────────────────────
    If the user is not authenticated AND the requested URL is not in
    PUBLIC_URL_PATTERNS, redirect to /login/?next=<original_path>.

    Stage 2 — Onboarding gate
    ──────────────────────────
    If the user IS authenticated but has no organization membership AND the
    requested URL is not in ONBOARDING_EXEMPT_PATTERNS, redirect to
    /create-organization/ so they complete onboarding before accessing the app.

    This ensures:
      Anonymous          → /login/
      Authenticated, no org → /create-organization/
      Authenticated, has org → application (normal flow)

    The middleware never creates redirect loops because:
      - /login/               is in PUBLIC_URL_PATTERNS
      - /create-organization/ is in ONBOARDING_EXEMPT_PATTERNS

    Must be placed in MIDDLEWARE **after**:
        django.contrib.auth.middleware.AuthenticationMiddleware
    because it relies on request.user.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.login_url = getattr(settings, "LOGIN_URL", "/login/")

    def __call__(self, request):
        path = request.path_info

        # ── Stage 1: authentication ──────────────────────────────────────────
        if not request.user.is_authenticated:
            if not _PUBLIC_RE.match(path):
                return redirect(f"{self.login_url}?next={request.get_full_path()}")
            return self.get_response(request)

        # ── Stage 2: onboarding gate ─────────────────────────────────────────
        # Import here to avoid circular import at module level (models are
        # not ready when middleware is first imported).
        from accounts.models import OrganizationMembership  # noqa: PLC0415

        if not _ONBOARDING_EXEMPT_RE.match(path):
            if not OrganizationMembership.objects.filter(
                user=request.user
            ).exists():
                return redirect(reverse("accounts:create_organization"))

        return self.get_response(request)

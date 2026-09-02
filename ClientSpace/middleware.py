import re

from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — URLs anonymous users may visit without authentication.
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
# Stage 2 — Onboarding gate: authenticated-but-not-yet-onboarded users.
# CLIENT users are created programmatically and never go through onboarding,
# so they must be exempt from this gate entirely.
# ─────────────────────────────────────────────────────────────────────────────
ONBOARDING_EXEMPT_PATTERNS = PUBLIC_URL_PATTERNS + [
    r"^/create-organization/$",
    r"^/logout/$",
]

# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Role guard: URLs that CLIENT users must NOT access.
# This is backend enforcement — hiding nav links is only UX sugar.
# ─────────────────────────────────────────────────────────────────────────────
CLIENT_BLOCKED_PATTERNS = [
    r"^/dashboard/",
    r"^/clients/",
    r"^/settings/",
    r"^/projects/create/",
]

_PUBLIC_RE = re.compile(
    "|".join(f"(?:{p})" for p in PUBLIC_URL_PATTERNS)
)
_ONBOARDING_EXEMPT_RE = re.compile(
    "|".join(f"(?:{p})" for p in ONBOARDING_EXEMPT_PATTERNS)
)
_CLIENT_BLOCKED_RE = re.compile(
    "|".join(f"(?:{p})" for p in CLIENT_BLOCKED_PATTERNS)
)


def _forbidden(request, reason="You do not have permission to access this page."):
    """Render the shared 403 template."""
    return render(request, "403.html", {"reason": reason}, status=403)


class LoginRequiredMiddleware:
    """
    Three-stage access gate that runs on every request.

    Stage 1 — Authentication gate
    ──────────────────────────────
    Unauthenticated + non-public URL  →  /login/?next=...

    Stage 2 — Onboarding gate
    ──────────────────────────
    Authenticated + no organisation + non-exempt URL  →  /create-organization/
    Skipped entirely for CLIENT role users (they never have an organisation).

    Stage 3 — Role guard
    ──────────────────────
    CLIENT role  +  management URL  →  403

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
        # CLIENT users are created by managers — they never go through the
        # organisation onboarding flow, so skip this gate for them entirely.
        if request.user.role != "CLIENT":
            from accounts.models import OrganizationMembership  # noqa: PLC0415

            if not _ONBOARDING_EXEMPT_RE.match(path):
                if not OrganizationMembership.objects.filter(
                    user=request.user
                ).exists():
                    return redirect(reverse("accounts:create_organization"))

        # ── Stage 3: CLIENT role guard ───────────────────────────────────────
        if request.user.role == "CLIENT" and _CLIENT_BLOCKED_RE.match(path):
            return _forbidden(
                request,
                "Clients do not have access to this section.",
            )

        return self.get_response(request)

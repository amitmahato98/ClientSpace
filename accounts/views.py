from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import (
    ForgotPasswordForm,
    LoginForm,
    OTPForm,
    OrganizationCreationForm,
    RegistrationForm,
    SetNewPasswordForm,
)
from .models import OTPCode, Organization, OrganizationMembership

User = get_user_model()


# ══════════════════════════════════════════════════════════════════════════════
# Helper utilities
# ══════════════════════════════════════════════════════════════════════════════

def _safe_next(request, fallback="/"):
    """
    Return the `next` URL from GET/POST only when it is safe (same host,
    not an external domain).  Falls back to `fallback`.
    """
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback


def user_has_organization(user) -> bool:
    """
    Return True if the user belongs to at least one organization.

    This is the canonical check used throughout the codebase.
    Always query membership records — never trust User.role alone.
    """
    return OrganizationMembership.objects.filter(user=user).exists()


def get_user_organization(user):
    """
    Return the first Organization the user belongs to, or None.

    For the initial release a user belongs to exactly one organization.
    Use the membership record rather than any user-supplied ID.
    """
    membership = (
        OrganizationMembership.objects
        .select_related("organization")
        .filter(user=user)
        .first()
    )
    return membership.organization if membership else None

def _post_login_redirect(request, user):
    if not user_has_organization(user):
        return reverse("accounts:create_organization")

    next_url = _safe_next(request, fallback=reverse("dashboard"))
    return next_url

def _send_otp_email(otp_obj, subject_prefix):
    """
    Send the OTP to the correct recipient via the configured SMTP backend.

    Sender    = DEFAULT_FROM_EMAIL from .env  (the Gmail account)
    Recipient = the email the user entered (pending_email or user.email)

    These are intentionally separate — the Gmail transport account is never
    automatically the recipient.
    """
    if otp_obj.pending_email:
        recipient = otp_obj.pending_email
    elif otp_obj.user and otp_obj.user.email:
        recipient = otp_obj.user.email
    else:
        return  # no valid recipient; abort silently

    from_addr = (
        django_settings.DEFAULT_FROM_EMAIL
        or django_settings.EMAIL_HOST_USER
    )

    send_mail(
        subject=f"[ClientSpace] {subject_prefix} — your verification code",
        message=(
            f"Your ClientSpace verification code is:\n\n"
            f"    {otp_obj.code}\n\n"
            f"This code expires in 10 minutes.\n"
            f"If you did not request this, please ignore this email.\n"
        ),
        from_email=from_addr,
        recipient_list=[recipient],
        fail_silently=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Login / Logout
# ══════════════════════════════════════════════════════════════════════════════

def login_view(request):
    """
    Authenticates the user with either email or username.

    Post-login redirect priority (enforced in _post_login_redirect):
      1. No organization → /create-organization/   (cannot be skipped)
      2. Safe `next` URL → redirect there
      3. Default → /dashboard/
    """
    if request.user.is_authenticated:
        return redirect(_post_login_redirect(request, request.user))

    form = LoginForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        identifier = form.cleaned_data["identifier"].strip()
        password = form.cleaned_data["password"]

        # Resolve email → username so Django's ModelBackend can find the user.
        username = identifier
        if "@" in identifier:
            try:
                user_obj = User.objects.get(email__iexact=identifier)
                username = user_obj.username
            except User.DoesNotExist:
                pass  # will fail authenticate() gracefully below

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_active:
                messages.error(
                    request,
                    "Your account has been deactivated. "
                    "Please contact an administrator.",
                )
            else:
                login(request, user)
                return redirect(_post_login_redirect(request, user))
        else:
            messages.error(
                request,
                "Invalid credentials. Please check your email/username and password.",
            )

    return render(request, "accounts/login.html", {
        "form": form,
        "next": request.GET.get("next", ""),
    })


def logout_view(request):
    """POST-only logout (CSRF-protected). Always redirects to login."""
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect(reverse("accounts:login"))


# ══════════════════════════════════════════════════════════════════════════════
# Registration — step 1: form
# ══════════════════════════════════════════════════════════════════════════════

def register_view(request):
    """
    Collects registration data, stores it in the server-side session, sends
    the OTP to the user's email, and redirects to OTP confirmation.

    The User record is NOT created here — only after OTP is verified.
    The role is assigned server-side (MANAGER); it is never read from POST.
    """
    if request.user.is_authenticated:
        return redirect(_post_login_redirect(request, request.user))

    form = RegistrationForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        cd = form.cleaned_data

        # Temporarily store registration data server-side (session only).
        # The raw password is held here only until OTP verification completes,
        # at which point it is immediately purged and hashed by create_user().
        request.session["pending_registration"] = {
            "username": cd["username"],
            "email": cd["email"].lower(),
            "first_name": cd["first_name"],
            "last_name": cd["last_name"],
            "password": cd["password1"],   # purged on successful OTP
        }

        otp = OTPCode.generate(
            purpose=OTPCode.Purpose.REGISTRATION,
            pending_email=cd["email"].lower(),
        )
        _send_otp_email(otp, subject_prefix="Confirm your registration")

        messages.info(
            request,
            "A 6-digit verification code has been sent to your email address.",
        )
        return redirect(reverse("accounts:register_otp"))

    return render(request, "accounts/register.html", {"form": form})


# ══════════════════════════════════════════════════════════════════════════════
# Registration — step 2: OTP verification
# ══════════════════════════════════════════════════════════════════════════════

def register_otp_view(request):
    """
    Verifies the registration OTP, creates the User account, then
    redirects to the organization setup page.

    Key rules:
      - User is created ONLY after OTP passes.
      - Role is always set to MANAGER — the first registrant owns their org.
      - Pending session data is purged immediately after create_user().
      - Raw password is never stored in the database.
    """
    pending = request.session.get("pending_registration")
    if not pending:
        messages.error(request, "No pending registration found. Please start again.")
        return redirect(reverse("accounts:register"))

    form = OTPForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        submitted_code = form.cleaned_data["otp"]
        email = pending["email"]

        try:
            otp_obj = OTPCode.objects.filter(
                pending_email=email,
                purpose=OTPCode.Purpose.REGISTRATION,
                is_used=False,
            ).latest("created_at")
        except OTPCode.DoesNotExist:
            messages.error(request, "Verification code not found. Please register again.")
            return redirect(reverse("accounts:register"))

        if otp_obj.is_expired():
            messages.error(
                request,
                "Your verification code has expired. Please register again.",
            )
            del request.session["pending_registration"]
            return redirect(reverse("accounts:register"))

        if not otp_obj.verify(submitted_code):
            messages.error(request, "Invalid verification code. Please try again.")
            return render(request, "accounts/register_otp.html", {
                "form": form,
                "email": email,
            })

        # ── OTP verified: create the account ─────────────────────────────
        # create_user() calls set_password() internally — raw password is
        # never persisted to the database.
        # Role = MANAGER because public registration creates organization owners.
        user = User.objects.create_user(
            username=pending["username"],
            email=pending["email"],
            password=pending["password"],   # hashed by create_user()
            first_name=pending["first_name"],
            last_name=pending["last_name"],
            role=User.Role.MANAGER,         # server-controlled; never from POST
            is_active=True,
        )

        # Purge the raw password from the session immediately.
        del request.session["pending_registration"]

        # Log the user in so the organization setup view can use request.user.
        login(request, user)

        messages.success(
            request,
            "Your account has been verified. Now set up your organization.",
        )
        return redirect(reverse("accounts:create_organization"))

    return render(request, "accounts/register_otp.html", {
        "form": form,
        "email": pending.get("email", ""),
    })


# ══════════════════════════════════════════════════════════════════════════════
# Organization setup (post-registration onboarding)
# ══════════════════════════════════════════════════════════════════════════════

@login_required
def create_organization_view(request):
    """
    Onboarding step for newly registered Managers.

    GET  → show the organization creation form.
    POST → validate, create Organization + OrganizationMembership atomically,
           then redirect to the dashboard.

    Guards:
      - Requires authentication (@login_required).
      - If the user already has an organization, redirect to dashboard
        immediately — prevents duplicate setup.
      - created_by and role are set server-side; never from POST data.
      - Organization + membership are created inside a single transaction
        so the database is never left in a half-created state.
    """
    # Already onboarded → skip straight to dashboard.
    if user_has_organization(request.user):
        return redirect(reverse("accounts:dashboard"))

    form = OrganizationCreationForm(
        request.POST or None,
        request.FILES or None,
    )

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                org = form.save(commit=False)
                # Trust only the authenticated session — never POST data.
                org.created_by = request.user
                org.save()

                OrganizationMembership.objects.create(
                    user=request.user,
                    organization=org,
                    role=OrganizationMembership.Role.MANAGER,
                )
        except Exception:
            messages.error(
                request,
                "Something went wrong while creating your organization. "
                "Please try again.",
            )
            return render(request, "accounts/create_organization.html", {"form": form})

        messages.success(
            request,
            f"Welcome to ClientSpace! Your organization \"{org.name}\" "
            f"has been created.",
        )
        return redirect(reverse("dashboard"))

    return render(request, "accounts/create_organization.html", {"form": form})


# ══════════════════════════════════════════════════════════════════════════════
# Forgot password — step 1: enter email
# ══════════════════════════════════════════════════════════════════════════════

def forgot_password_view(request):
    """
    Accepts an email address and sends a password-reset OTP if an account
    exists for that address.  Response is identical whether the email is
    found or not (prevents user enumeration).
    """
    if request.user.is_authenticated:
        return redirect(_post_login_redirect(request, request.user))

    form = ForgotPasswordForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            user = None

        if user and user.is_active:
            otp = OTPCode.generate(
                purpose=OTPCode.Purpose.PASSWORD_RESET,
                user=user,
            )
            _send_otp_email(otp, subject_prefix="Reset your password")
            request.session["pw_reset_user_pk"] = user.pk

        messages.info(
            request,
            "If an account exists for that email address, a reset code "
            "has been sent.",
        )
        return redirect(reverse("accounts:forgot_password_otp"))

    return render(request, "accounts/forgot_password.html", {"form": form})


# ══════════════════════════════════════════════════════════════════════════════
# Forgot password — step 2: OTP verification
# ══════════════════════════════════════════════════════════════════════════════

def forgot_password_otp_view(request):
    """Validates the password-reset OTP and marks the session as verified."""
    user_pk = request.session.get("pw_reset_user_pk")
    if not user_pk:
        messages.error(request, "Session expired. Please restart the password reset.")
        return redirect(reverse("accounts:forgot_password"))

    form = OTPForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        submitted_code = form.cleaned_data["otp"]

        try:
            user = User.objects.get(pk=user_pk)
        except User.DoesNotExist:
            messages.error(request, "User not found. Please try again.")
            return redirect(reverse("accounts:forgot_password"))

        try:
            otp_obj = OTPCode.objects.filter(
                user=user,
                purpose=OTPCode.Purpose.PASSWORD_RESET,
                is_used=False,
            ).latest("created_at")
        except OTPCode.DoesNotExist:
            messages.error(
                request,
                "No active reset code found. Please request a new one.",
            )
            return redirect(reverse("accounts:forgot_password"))

        if otp_obj.is_expired():
            messages.error(
                request,
                "Your reset code has expired. Please request a new one.",
            )
            return redirect(reverse("accounts:forgot_password"))

        if not otp_obj.verify(submitted_code):
            messages.error(request, "Invalid code. Please try again.")
            return render(request, "accounts/forgot_password_otp.html", {"form": form})

        request.session["pw_reset_verified"] = True
        return redirect(reverse("accounts:set_new_password"))

    return render(request, "accounts/forgot_password_otp.html", {"form": form})


# ══════════════════════════════════════════════════════════════════════════════
# Forgot password — step 3: set new password
# ══════════════════════════════════════════════════════════════════════════════

def set_new_password_view(request):
    """
    Sets a new password after OTP verification.
    Always uses user.set_password() — raw passwords are never stored.
    """
    user_pk = request.session.get("pw_reset_user_pk")
    verified = request.session.get("pw_reset_verified", False)

    if not user_pk or not verified:
        messages.error(request, "Invalid or expired session. Please start over.")
        return redirect(reverse("accounts:forgot_password"))

    form = SetNewPasswordForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            user = User.objects.get(pk=user_pk)
        except User.DoesNotExist:
            messages.error(request, "User not found.")
            return redirect(reverse("accounts:forgot_password"))

        # set_password() hashes via Django's password hasher.
        # NEVER do: user.password = raw_password
        user.set_password(form.cleaned_data["password1"])
        user.save(update_fields=["password"])

        for key in ("pw_reset_user_pk", "pw_reset_verified"):
            request.session.pop(key, None)

        messages.success(
            request,
            "Your password has been updated. You can now sign in.",
        )
        return redirect(reverse("accounts:login"))

    return render(request, "accounts/set_new_password.html", {"form": form})


# ══════════════════════════════════════════════════════════════════════════════
# Google OAuth placeholder
# ══════════════════════════════════════════════════════════════════════════════

def google_login(request):
    """
    Placeholder — Google OAuth is not yet configured.
    Implement via django-allauth or social-auth-app-django when ready.
    """
    messages.info(
        request,
        "Google sign-in is not yet available. Please use email and password.",
    )
    return redirect(reverse("accounts:login"))


# ══════════════════════════════════════════════════════════════════════════════
# Dashboard
# ══════════════════════════════════════════════════════════════════════════════

@login_required
def dashboard_view(request):
    """
    Authenticated landing page.

    A user with no organization should never reach this view because the
    middleware redirects them to /create-organization/ first, but we add
    a safety check here as a second line of defence.
    """
    if not user_has_organization(request.user):
        return redirect(reverse("accounts:create_organization"))

    organization = get_user_organization(request.user)
    return render(request, "base.html", {"organization": organization})

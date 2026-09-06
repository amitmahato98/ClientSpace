import logging
import secrets
import string

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as tz

from accounts.decorators import manager_required
from accounts.models import OrganizationMembership
from accounts.views import get_user_organization
from .forms import ProjectForm, ProjectStaffAssignForm
from .models import Project

User = get_user_model()
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Password generator
# ──────────────────────────────────────────────────────────────────────────────

def _generate_temp_password(length: int = 14) -> str:
    """
    Cryptographically secure random temporary password.

    Uses secrets.choice() (backed by os.urandom()).  Guarantees at least one
    character from each class so the password satisfies common policies.
    """
    lower   = string.ascii_lowercase
    upper   = string.ascii_uppercase
    digits  = string.digits
    special = "!@#$%^&*"
    alphabet = lower + upper + digits + special

    mandatory = [
        secrets.choice(lower),
        secrets.choice(upper),
        secrets.choice(digits),
        secrets.choice(special),
    ]
    rest = [secrets.choice(alphabet) for _ in range(length - len(mandatory))]
    combined = mandatory + rest
    secrets.SystemRandom().shuffle(combined)
    return "".join(combined)


# ──────────────────────────────────────────────────────────────────────────────
# Email helpers
# ──────────────────────────────────────────────────────────────────────────────

def _send_client_welcome_email(
    *,
    client_email: str,
    client_username: str,
    temp_password: str,
    project_name: str,
    organization_name: str,
    login_url: str,
) -> None:
    """
    Send the welcome / credentials email to a newly created Client.

    Only called via transaction.on_commit() so the email is never dispatched
    before the database row is safely committed.
    """
    from_addr = (
        django_settings.DEFAULT_FROM_EMAIL
        or django_settings.EMAIL_HOST_USER
    )

    subject = "Welcome to ClientSpace — Your Project Access"
    body = (
        f"Hello,\n\n"
        f"A ClientSpace account has been created for you by {organization_name}.\n\n"
        f"Your login credentials are:\n\n"
        f"    Username:           {client_username}\n"
        f"    Temporary password: {temp_password}\n\n"
        f"Project: {project_name}\n\n"
        f"Sign in here: {login_url}\n\n"
        f"After logging in you will be able to view your project information "
        f"and track project progress.\n\n"
        f"You do not need to create an organisation — your account has already "
        f"been associated with {organization_name} and your project.\n\n"
        f"For security, please change your password after your first login.\n\n"
        f"Regards,\n"
        f"ClientSpace Team\n"
    )

    send_mail(
        subject=subject,
        message=body,
        from_email=from_addr,
        recipient_list=[client_email],
        fail_silently=False,
    )


def _send_project_notification_email(
    *,
    client_email: str,
    client_username: str,
    project_name: str,
    organization_name: str,
    login_url: str,
) -> None:
    """
    Notify an *existing* client that a new project has been assigned to them.

    No credentials are included because the client already has an account.
    """
    from_addr = (
        django_settings.DEFAULT_FROM_EMAIL
        or django_settings.EMAIL_HOST_USER
    )

    subject = f"ClientSpace — New project assigned: {project_name}"
    body = (
        f"Hello {client_username},\n\n"
        f"A new project has been assigned to your ClientSpace account by "
        f"{organization_name}.\n\n"
        f"Project: {project_name}\n\n"
        f"Sign in to view your project: {login_url}\n\n"
        f"Regards,\n"
        f"ClientSpace Team\n"
    )

    send_mail(
        subject=subject,
        message=body,
        from_email=from_addr,
        recipient_list=[client_email],
        fail_silently=False,
    )


# ──────────────────────────────────────────────────────────────────────────────
# PROJECT LIST
# ──────────────────────────────────────────────────────────────────────────────

@login_required
def project_list(request):
    """
    Show projects appropriate to the logged-in user's role.

    MANAGER / STAFF  → all projects (scoped to their org where applicable)
    CLIENT           → only projects where project.client == request.user
    """
    if request.user.is_client:
        projects = (
            Project.objects
            .select_related("client", "created_by", "organization")
            .filter(client=request.user)
        )
    else:
        projects = (
            Project.objects
            .select_related("client", "created_by", "organization")
            .all()
        )

    return render(request, "projects/projects.html", {"projects": projects})


# ──────────────────────────────────────────────────────────────────────────────
# PROJECT CREATE  — MANAGER ONLY
# ──────────────────────────────────────────────────────────────────────────────

@manager_required
def project_create(request):
    """
    GET  → display the blank project creation form.
    POST → inside a single transaction.atomic():

    CREATE mode (new client username + email):
        1. Generate secure temp password
        2. Create accounts.User  (role=CLIENT, password hashed by create_user())
        3. Create OrganizationMembership  (client → manager's org, role=CLIENT)
        4. Create Project  (client=new user, organization=manager's org)
        5. on_commit: send welcome email with credentials

    REUSE mode (existing CLIENT username + email, same user):
        1. Resolve existing client user from form
        2. Ensure OrganizationMembership exists  (get_or_create — idempotent)
        3. Create Project  (client=existing user, organization=manager's org)
        4. on_commit: send new-project notification email (no credentials)

    In both modes:
        - created_by  = request.user          (server-side only)
        - organization = manager's org         (server-side only)
        - client       = resolved client user  (server-side only)
        None of these are read from POST data.

    The @manager_required decorator renders 403.html for STAFF and CLIENT
    so they can never reach this view even by direct URL entry.
    """
    # Resolve the manager's organisation up front so we can surface a clear
    # error immediately if the manager somehow has no org (shouldn't happen
    # in normal flow but defensive programming is worthwhile).
    from accounts.models import OrganizationMembership

    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(
            request,
            "You must set up your organisation before creating projects. "
            "Please complete the onboarding step first.",
        )
        return redirect(reverse("accounts:create_organization"))

    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            cd               = form.cleaned_data
            client_mode      = form.client_mode           # "create" | "reuse"
            existing_client  = form.existing_client_user  # User | None
            client_username  = cd["client_username"]
            client_email     = cd["client_email"]
            project_name     = cd["name"]
            org_name         = manager_org.name

            login_url = request.build_absolute_uri(reverse("accounts:login"))

            # Temp password only needed (and generated) for CREATE mode.
            temp_password = _generate_temp_password() if client_mode == "create" else None

            try:
                with transaction.atomic():

                    # ── Resolve / create the client user ──────────────────
                    if client_mode == "create":
                        client_user = User.objects.create_user(
                            username  = client_username,
                            email     = client_email,
                            password  = temp_password,       # hashed by create_user()
                            role      = User.Role.CLIENT,
                            is_active = True,
                        )
                        # temp_password lives only in local memory until the
                        # on_commit closure fires; it is never stored in the DB.
                    else:
                        # REUSE mode — existing CLIENT account
                        client_user = existing_client

                    # ── Ensure the client belongs to the manager's org ─────
                    # get_or_create is idempotent — safe to call even if the
                    # membership already exists from a previous project.
                    OrganizationMembership.objects.get_or_create(
                        user         = client_user,
                        organization = manager_org,
                        defaults     = {"role": OrganizationMembership.Role.CLIENT},
                    )

                    # ── Create the project ────────────────────────────────
                    project = form.save(commit=False)
                    project.client       = client_user    # server-side only
                    project.created_by   = request.user  # server-side only
                    project.organization = manager_org   # server-side only
                    project.save()

                    # ── Schedule the outbound email after commit ──────────
                    # Capture all values in the closure NOW, before the
                    # request object may be recycled.
                    if client_mode == "create":
                        def _send_email(
                            _email    = client_email,
                            _username = client_username,
                            _pwd      = temp_password,
                            _proj     = project_name,
                            _org      = org_name,
                            _url      = login_url,
                        ):
                            try:
                                _send_client_welcome_email(
                                    client_email      = _email,
                                    client_username   = _username,
                                    temp_password     = _pwd,
                                    project_name      = _proj,
                                    organization_name = _org,
                                    login_url         = _url,
                                )
                            except Exception as exc:
                                logger.error(
                                    "Failed to send welcome email to %s: %s",
                                    _email, exc,
                                )
                    else:
                        def _send_email(
                            _email    = client_email,
                            _username = client_username,
                            _proj     = project_name,
                            _org      = org_name,
                            _url      = login_url,
                        ):
                            try:
                                _send_project_notification_email(
                                    client_email      = _email,
                                    client_username   = _username,
                                    project_name      = _proj,
                                    organization_name = _org,
                                    login_url         = _url,
                                )
                            except Exception as exc:
                                logger.error(
                                    "Failed to send project notification to %s: %s",
                                    _email, exc,
                                )

                    transaction.on_commit(_send_email)

            except Exception as exc:
                logger.error("project_create failed: %s", exc)
                messages.error(
                    request,
                    "Something went wrong while creating the project. "
                    "Please try again.",
                )
                return render(request, "projects/project_form.html", {"form": form})

            if client_mode == "create":
                success_msg = (
                    f'Project "{project.name}" created successfully. '
                    f'A new client account has been created and login credentials '
                    f'have been emailed to {client_email}.'
                )
            else:
                success_msg = (
                    f'Project "{project.name}" created successfully. '
                    f'It has been assigned to the existing client '
                    f'"{client_username}".'
                )

            messages.success(request, success_msg)
            return redirect("projects:project_list")

    else:
        form = ProjectForm()

    return render(request, "projects/project_form.html", {"form": form})


# ──────────────────────────────────────────────────────────────────────────────
# PROJECT DETAIL
# ──────────────────────────────────────────────────────────────────────────────

@login_required
def project_detail(request, pk):
    """
    Display details for a single project loaded from the database.

    Authorization:
      MANAGER / STAFF  → can view any project
      CLIENT           → can only view projects where project.client == request.user
                         silently 404s on mismatch to avoid leaking existence

    Context extras for staff assignment UI (MANAGER only):
      assigned_staff   — active StaffAssignment queryset for this project
      assign_form      — ProjectStaffAssignForm (blank) for the modal
    """
    from staff.models import StaffAssignment

    qs = Project.objects.select_related("client", "created_by", "organization")

    if request.user.is_client:
        project = get_object_or_404(qs, pk=pk, client=request.user)
    else:
        project = get_object_or_404(qs, pk=pk)

    # Assigned staff — always load so STAFF/CLIENT can see the list (read-only)
    assigned_staff = (
        StaffAssignment.objects
        .filter(project=project, is_active=True)
        .select_related("staff", "staff__user")
        .order_by("assigned_at")
    )

    # Assign form — only built for managers (avoids unnecessary query for others)
    assign_form = None
    if request.user.is_manager and project.organization:
        assign_form = ProjectStaffAssignForm(
            project=project,
            organization=project.organization,
        )

    return render(request, "projects/projectdetails.html", {
        "project": project,
        "assigned_staff": assigned_staff,
        "assign_form": assign_form,
    })


# ──────────────────────────────────────────────────────────────────────────────
# ASSIGN STAFF  — MANAGER ONLY
# ──────────────────────────────────────────────────────────────────────────────

@manager_required
def assign_staff(request, pk):
    """
    POST-only endpoint.  Assigns one or more eligible Staff members to the
    given project by creating StaffAssignment records.

    Authorization chain (all enforced server-side):
      1. @manager_required  →  must be authenticated + MANAGER role
      2. Project must exist
      3. Project must belong to the manager's organisation
      4. Every submitted staff ID is validated against the eligible queryset
         (same org, has account, not already assigned) by ProjectStaffAssignForm

    Duplicate-safe: because we exclude already-active assignments from the
    eligible queryset, a staff member who is already assigned cannot be
    selected — the form will reject the submission if someone forges the POST.
    """
    from staff.models import StaffAssignment

    if request.method != "POST":
        return redirect("projects:project_detail", pk=pk)

    # ── Resolve manager's organisation ───────────────────────────────────────
    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(request, "You must belong to an organisation to assign staff.")
        return redirect("projects:project_detail", pk=pk)

    # ── Load & authorise project ──────────────────────────────────────────────
    project = get_object_or_404(
        Project,
        pk=pk,
        organization=manager_org,   # cross-org attack prevention
    )

    # ── Validate submitted staff IDs ─────────────────────────────────────────
    form = ProjectStaffAssignForm(
        request.POST,
        project=project,
        organization=manager_org,
    )

    if not form.is_valid():
        # Collect the first meaningful error to surface via messages
        error_text = " ".join(
            str(e)
            for field_errors in form.errors.values()
            for e in field_errors
        )
        messages.error(request, error_text or "Invalid staff selection.")
        return redirect("projects:project_detail", pk=pk)

    eligible_staff = form.cleaned_data["staff_ids"]   # validated Staff QS items

    newly_assigned = []
    for staff_member in eligible_staff:
        # Final duplicate guard: skip if an active assignment already exists.
        # This handles the race where two requests land simultaneously.
        _, created = StaffAssignment.objects.get_or_create(
            staff=staff_member,
            project=project,
            is_active=True,
            defaults={
                "work": "Assigned to project",
                "assigned_by": request.user,
            },
        )
        if created:
            newly_assigned.append(staff_member)

    if newly_assigned:
        if len(newly_assigned) == 1:
            name = f"{newly_assigned[0].first_name} {newly_assigned[0].last_name}".strip()
            messages.success(request, f"{name} was assigned to this project.")
        else:
            names = ", ".join(
                f"{s.first_name} {s.last_name}".strip() for s in newly_assigned
            )
            messages.success(request, f"{len(newly_assigned)} staff members assigned: {names}.")
    else:
        messages.info(request, "No new staff were assigned (already assigned or none selected).")

    return redirect("projects:project_detail", pk=pk)


# ──────────────────────────────────────────────────────────────────────────────
# REMOVE STAFF  — MANAGER ONLY
# ──────────────────────────────────────────────────────────────────────────────

@manager_required
def remove_staff(request, pk, assignment_id):
    """
    POST-only endpoint.  Removes a Staff member from a project by marking
    the StaffAssignment as inactive.

    This does NOT delete the User, deactivate the Staff account, delete
    the Project, or remove the staff member's organisation membership.
    It only marks the Project ↔ Staff relationship as inactive.

    Authorization chain:
      1. @manager_required
      2. Project must belong to the manager's organisation
      3. StaffAssignment must belong to that project
    """
    from staff.models import StaffAssignment

    if request.method != "POST":
        return redirect("projects:project_detail", pk=pk)

    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(request, "You must belong to an organisation to manage staff.")
        return redirect("projects:project_detail", pk=pk)

    project = get_object_or_404(
        Project,
        pk=pk,
        organization=manager_org,
    )

    assignment = get_object_or_404(
        StaffAssignment,
        pk=assignment_id,
        project=project,        # must belong to this project
        is_active=True,
    )

    staff_name = f"{assignment.staff.first_name} {assignment.staff.last_name}".strip()

    assignment.is_active = False
    assignment.completed_at = tz.now()
    assignment.save(update_fields=["is_active", "completed_at"])

    messages.success(request, f"{staff_name} has been removed from this project.")
    return redirect("projects:project_detail", pk=pk)

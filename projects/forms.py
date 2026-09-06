import re

from django import forms
from django.contrib.auth import get_user_model

from .models import Project

User = get_user_model()

# ---------------------------------------------------------------------------
# Imported lazily to avoid circular imports at module load time.
# Staff and StaffAssignment live in the staff app; we import them inside the
# form class so there is no import-time coupling.
# ---------------------------------------------------------------------------

# Shared Tailwind input classes used across all widgets
_INPUT = (
    "w-full px-3.5 py-2.5 text-sm rounded-lg border border-gray-200 "
    "bg-white focus:outline-none focus:ring-2 focus:ring-[#d4a373]/30 "
    "focus:border-[#d4a373] transition"
)
_SELECT = _INPUT
_TEXTAREA = (
    "w-full px-3.5 py-2.5 text-sm rounded-lg border border-gray-200 "
    "bg-white focus:outline-none focus:ring-2 focus:ring-[#d4a373]/30 "
    "focus:border-[#d4a373] transition resize-none"
)


class ProjectForm(forms.ModelForm):
    """
    Manager-facing form for creating a new Project together with a
    Client user account.

    Extra non-model fields
    ─────────────────────
    client_username  — username for the Client account
    client_email     — email address for the Client account

    Two modes resolved during form validation
    ─────────────────────────────────────────
    CREATE mode  — neither username nor email exist yet.
                   A new accounts.User (role=CLIENT) will be created in the
                   view, a temporary password generated, and a welcome email sent.

    REUSE mode   — username AND email both belong to the SAME existing CLIENT
                   user.  The existing account is attached to the new project;
                   no new user, no new password, no email is sent.

    Hard errors (form never valid)
    ──────────────────────────────
    • Either field belongs to a MANAGER or STAFF account — role must never
      be changed.
    • Username belongs to one CLIENT and email belongs to a different CLIENT
      — ambiguous; manager must clarify.
    • Username is a new value but email already belongs to a different CLIENT
      (or vice-versa) — mismatch between the two reuse signals.

    Fields set server-side (never from POST)
    ────────────────────────────────────────
    client      — set to the resolved/created User in the view
    created_by  — set to request.user in the view
    organization — set to manager's org in the view
    created_at / updated_at — auto
    """

    # ── Extra fields (not on the model) ──────────────────────────────────
    client_username = forms.CharField(
        max_length=150,
        label="Client username",
        widget=forms.TextInput(attrs={
            "placeholder": "e.g. john_smith",
            "class": _INPUT,
            "autocomplete": "off",
        }),
        help_text="Username for the client's ClientSpace login.",
    )

    client_email = forms.EmailField(
        label="Client Gmail / email",
        widget=forms.EmailInput(attrs={
            "placeholder": "e.g. client@gmail.com",
            "class": _INPUT,
            "autocomplete": "off",
        }),
        help_text="Credentials will be sent here (new clients only).",
    )

    class Meta:
        model = Project
        # client, created_by, organization are set server-side in the view.
        fields = [
            "name",
            "description",
            "status",
            "priority",
            "budget",
            "start_date",
            "deadline",
        ]
        widgets = {
            "name": forms.TextInput(attrs={
                "placeholder": "e.g. Website redesign",
                "class": _INPUT,
            }),
            "description": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Anything the team should know...",
                "class": _TEXTAREA,
            }),
            "status":    forms.Select(attrs={"class": _SELECT}),
            "priority":  forms.Select(attrs={"class": _SELECT}),
            "budget":    forms.NumberInput(attrs={
                "min": "0",
                "step": "0.01",
                "placeholder": "0.00",
                "class": _INPUT,
            }),
            "start_date": forms.DateInput(attrs={"type": "date", "class": _INPUT}),
            "deadline":   forms.DateInput(attrs={"type": "date", "class": _INPUT}),
        }
        labels = {
            "name":        "Project name",
            "description": "Description (optional)",
            "status":      "Status",
            "priority":    "Priority",
            "budget":      "Budget ($)",
            "start_date":  "Start date",
            "deadline":    "Deadline",
        }

    # ── Field-level validation ────────────────────────────────────────────

    def clean_client_username(self):
        username = self.cleaned_data.get("client_username", "").strip()

        if not re.match(r'^[\w.@+-]+$', username):
            raise forms.ValidationError(
                "Username may only contain letters, digits, and @/./+/-/_ characters."
            )

        try:
            existing = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            # New username — fine for CREATE mode.
            return username

        # Username already exists — check the role.
        if existing.role != User.Role.CLIENT:
            raise forms.ValidationError(
                f"This username belongs to an existing {existing.get_role_display()} "
                f"account. It cannot be used for a client."
            )

        # Existing CLIENT username — store the user object for cross-validation.
        # Django ModelForm stores cleaned_data values; we store the User instance
        # so clean() can retrieve it without a second query.
        self._username_user = existing
        return username

    def clean_client_email(self):
        email = self.cleaned_data.get("client_email", "").lower().strip()

        try:
            existing = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # New email — fine for CREATE mode.
            return email

        # Email already exists — check the role.
        if existing.role != User.Role.CLIENT:
            raise forms.ValidationError(
                f"This email address belongs to an existing "
                f"{existing.get_role_display()} account. "
                f"It cannot be used for a client."
            )

        # Existing CLIENT email — stash the user for cross-validation.
        self._email_user = existing
        return email

    def clean(self):
        """
        Cross-field validation to resolve CREATE vs REUSE mode and detect
        ambiguous / mismatched inputs.

        After this method, self.client_mode is set to either:
            "create"  — both username and email are new; view must create user
            "reuse"   — both point to the same existing CLIENT; view must reuse
        and self.existing_client_user is set to the User instance for reuse mode,
        or None for create mode.
        """
        cleaned = super().clean()

        username_user = getattr(self, "_username_user", None)  # set in clean_client_username
        email_user    = getattr(self, "_email_user",    None)  # set in clean_client_email

        both_new      = (username_user is None and email_user is None)
        both_existing = (username_user is not None and email_user is not None)
        one_existing  = not both_new and not both_existing

        if both_new:
            # CREATE mode — standard path: new user will be created in the view.
            self.client_mode = "create"
            self.existing_client_user = None

        elif both_existing:
            if username_user.pk != email_user.pk:
                # The username belongs to Client A and the email to Client B.
                raise forms.ValidationError(
                    "The username and email address belong to different existing "
                    "client accounts. Please provide matching credentials for a "
                    "single client, or use a new username and email to create a "
                    "new account."
                )
            # REUSE mode — same existing CLIENT.
            self.client_mode = "reuse"
            self.existing_client_user = username_user

        else:
            # One field is new, the other already exists — mismatch.
            if username_user is not None:
                raise forms.ValidationError(
                    "The username belongs to an existing client account but the "
                    "email address is new. To reuse an existing client, both the "
                    "username and email must match their existing account."
                )
            else:
                raise forms.ValidationError(
                    "The email address belongs to an existing client account but "
                    "the username is new. To reuse an existing client, both the "
                    "username and email must match their existing account."
                )

        return cleaned


# ═══════════════════════════════════════════════════════════════════════════
# ProjectStaffAssignForm
# ═══════════════════════════════════════════════════════════════════════════

class ProjectStaffAssignForm(forms.Form):
    """
    Manager-facing form for assigning one or more Staff members to a project.

    Security guarantees
    ───────────────────
    • The eligible Staff queryset is built server-side from the project's
      organization. Only Staff whose user account exists (user__isnull=False)
      and who belong to the same organization as the project are eligible.
    • Already-active assignments are excluded so the same staff member cannot
      be assigned twice to the same project.
    • Every submitted staff ID is validated against the eligible queryset
      inside clean_staff_ids(). A malicious POST with an out-of-org ID is
      rejected with a form error before any database write occurs.

    Usage
    ─────
        form = ProjectStaffAssignForm(
            project=project,
            organization=project.organization,
            data=request.POST or None,
        )
    """

    # Populated dynamically in __init__ — widget rendered in template manually
    # so we can style the checkboxes to match the existing Tailwind design.
    staff_ids = forms.ModelMultipleChoiceField(
        queryset=None,          # set in __init__
        required=True,
        error_messages={
            "required": "Please select at least one staff member to assign.",
            "invalid_choice": "One or more selected staff members are not eligible.",
            "invalid_pk_value": "Invalid staff selection.",
        },
    )

    def __init__(self, *args, project, organization, **kwargs):
        super().__init__(*args, **kwargs)

        # Import here to avoid circular dependency at module level.
        from staff.models import Staff, StaffAssignment

        # IDs of staff already actively assigned to this project — excluded
        # so the UI shows them as "already assigned" and they cannot be added twice.
        already_assigned_ids = StaffAssignment.objects.filter(
            project=project,
            is_active=True,
        ).values_list("staff_id", flat=True)

        eligible_qs = (
            Staff.objects
            .filter(
                organization=organization,
                user__isnull=False,     # only staff who have completed setup
            )
            .exclude(id__in=already_assigned_ids)
            .select_related("user")
            .order_by("first_name", "last_name")
        )

        self.fields["staff_ids"].queryset = eligible_qs

        # Store on self so the view can access it for the "already assigned"
        # display list without running another query.
        self.already_assigned_ids = list(already_assigned_ids)
        self.eligible_qs = eligible_qs

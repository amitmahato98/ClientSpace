from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()


# ─────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────

class LoginForm(forms.Form):
    """
    Accepts either a username or an email address in the identifier field.
    The view resolves which one it is.
    """
    identifier = forms.CharField(
        label="Email or Username",
        max_length=254,
        widget=forms.TextInput(attrs={
            "class": "form-input",
            "placeholder": "Enter your email or username",
            "autocomplete": "username",
        }),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-input",
            "placeholder": "Enter your password",
            "autocomplete": "current-password",
        }),
    )


# ─────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────

class RegistrationForm(forms.Form):
    """
    Public registration form.  Always creates a CLIENT account.
    The role field is NOT exposed here — the view sets it server-side.
    """
    first_name = forms.CharField(
        label="First name",
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "form-input",
            "placeholder": "First name",
            "autocomplete": "given-name",
        }),
    )
    last_name = forms.CharField(
        label="Last name",
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "form-input",
            "placeholder": "Last name",
            "autocomplete": "family-name",
        }),
    )
    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={
            "class": "form-input",
            "placeholder": "Enter your email address",
            "autocomplete": "email",
        }),
    )
    username = forms.CharField(
        label="Username",
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "form-input",
            "placeholder": "Choose a username",
            "autocomplete": "username",
        }),
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-input",
            "placeholder": "Create password",
            "autocomplete": "new-password",
        }),
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={
            "class": "form-input",
            "placeholder": "Confirm password",
            "autocomplete": "new-password",
        }),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email=email).exists():
            raise ValidationError("An account with this email address already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("This username is already taken.")
        return username

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        if password:
            validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned


# ─────────────────────────────────────────────
# OTP entry (used for both registration & password-reset)
# ─────────────────────────────────────────────

class OTPForm(forms.Form):
    otp = forms.CharField(
        label="Verification code",
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            "class": "form-input",
            "placeholder": "Enter 6-digit code",
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
            "pattern": "[0-9]{6}",
        }),
    )

    def clean_otp(self):
        code = self.cleaned_data["otp"].strip()
        if not code.isdigit():
            raise ValidationError("The verification code must be 6 digits.")
        return code


# ─────────────────────────────────────────────
# Forgot password — step 1: enter email
# ─────────────────────────────────────────────

class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={
            "class": "form-input",
            "placeholder": "Enter your email address",
            "autocomplete": "email",
        }),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        # We deliberately do NOT raise an error when the email is not found.
        # This prevents user-enumeration attacks.  The view handles the
        # "not found" case silently.
        return email


# ─────────────────────────────────────────────
# Set new password (after OTP verified)
# ─────────────────────────────────────────────

class SetNewPasswordForm(forms.Form):
    password1 = forms.CharField(
        label="New password",
        widget=forms.PasswordInput(attrs={
            "class": "form-input",
            "placeholder": "Enter new password",
            "autocomplete": "new-password",
        }),
    )
    password2 = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput(attrs={
            "class": "form-input",
            "placeholder": "Confirm new password",
            "autocomplete": "new-password",
        }),
    )

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        if password:
            validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned


# ─────────────────────────────────────────────
# Organization creation (post-registration)
# ─────────────────────────────────────────────

from .models import Organization  # noqa: E402  (imported here to avoid circular at top)


class OrganizationCreationForm(forms.ModelForm):
    """
    Used by a newly registered Manager to create their organization.

    Fields intentionally excluded from the form:
      - slug        → generated automatically from the name in Organization.save()
      - created_by  → set from request.user in the view (never from POST data)
      - created_at / updated_at → auto fields

    All trust-sensitive assignments happen server-side.
    """

    class Meta:
        model = Organization
        fields = [
            "name",
            "description",
            "email",
            "phone",
            "address",
            "website",
            "logo",
        ]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "Your company or team name",
                "autofocus": True,
            }),
            "description": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": "Brief description of your organization (optional)",
                "rows": 3,
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-input",
                "placeholder": "Organization contact email (optional)",
            }),
            "phone": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "Phone number (optional)",
            }),
            "address": forms.Textarea(attrs={
                "class": "form-input",
                "placeholder": "Office address (optional)",
                "rows": 2,
            }),
            "website": forms.URLInput(attrs={
                "class": "form-input",
                "placeholder": "https://yourwebsite.com (optional)",
            }),
        }

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if not name:
            raise ValidationError("Organization name is required.")
        return name

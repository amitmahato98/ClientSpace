import secrets
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class User(AbstractUser):
    """
    Custom user model for ClientSpace.
    Replaces the default Django User with role-based access control.
    """

    class Role(models.TextChoices):
        MANAGER = "MANAGER", "Manager"
        STAFF = "STAFF", "Staff"
        CLIENT = "CLIENT", "Client"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CLIENT,
    )

    # Email is required and unique across the system.
    email = models.EmailField(unique=True, verbose_name="email address")

    display_name = models.CharField(max_length=150, blank=True, default="")
    profile_picture = models.ImageField(
        upload_to="profile_pictures/",
        blank=True,
        null=True,
    )

    # AbstractUser already provides: username, first_name, last_name,
    # password, is_active, is_staff, is_superuser, date_joined, last_login,
    # groups, user_permissions.

    def __str__(self):
        return self.display_name or self.username or self.email

    @property
    def initials(self):
        name = self.display_name or self.get_full_name() or self.username or "User"
        parts = name.strip().split()
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}".upper()
        return name[:2].upper()


    # ------------------------------------------------------------------ #
    # Convenience role-check properties                                    #
    # ------------------------------------------------------------------ #

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER

    @property
    def is_staff_member(self):
        """
        Distinct from Django's built-in is_staff (admin access).
        Returns True when the user has the STAFF application role.
        """
        return self.role == self.Role.STAFF

    @property
    def is_client(self):
        return self.role == self.Role.CLIENT


class OTPCode(models.Model):
    """
    Single-use, time-limited OTP.

    Used for two flows:
      - Registration confirmation  (user is NULL, email stored separately)
      - Forgot-password reset      (user is set)

    The OTP itself is a 6-digit string generated with secrets.randbelow()
    so it is cryptographically random.
    """

    class Purpose(models.TextChoices):
        REGISTRATION = "registration", "Registration"
        PASSWORD_RESET = "password_reset", "Password Reset"

    # For password-reset the OTP is tied to an existing user.
    # For registration the user does not exist yet; we leave user NULL
    # and store the email in pending_email instead.
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="otp_codes",
    )

    # Holds the email for pre-registration OTP verification when user=NULL.
    pending_email = models.EmailField(blank=True, default="")

    purpose = models.CharField(
        max_length=20,
        choices=Purpose.choices,
        default=Purpose.REGISTRATION,
    )

    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(default=timezone.now)
    is_used = models.BooleanField(default=False)

    # OTP expires after this many seconds (10 minutes).
    EXPIRY_SECONDS = 600

    class Meta:
        verbose_name = "OTP Code"
        verbose_name_plural = "OTP Codes"

    def __str__(self):
        target = self.user.username if self.user else self.pending_email
        return f"OTP({self.purpose}) for {target}"

    @classmethod
    def generate(cls, purpose, user=None, pending_email=""):
        """
        Invalidate any existing unexpired OTPs for the same target,
        then create and return a new one.
        """
        code = str(secrets.randbelow(900000) + 100000)  # 100000-999999

        # Invalidate previous OTPs for this target + purpose.
        if user:
            cls.objects.filter(user=user, purpose=purpose, is_used=False).update(
                is_used=True
            )
        elif pending_email:
            cls.objects.filter(
                pending_email=pending_email, purpose=purpose, is_used=False
            ).update(is_used=True)

        return cls.objects.create(
            user=user,
            pending_email=pending_email,
            purpose=purpose,
            code=code,
        )

    def is_expired(self):
        return (timezone.now() - self.created_at).total_seconds() > self.EXPIRY_SECONDS

    def verify(self, submitted_code):
        """
        Returns True and marks as used if the code matches and is not
        expired or already used.  Returns False otherwise.
        """
        if self.is_used or self.is_expired():
            return False
        if self.code != submitted_code:
            return False
        self.is_used = True
        self.save(update_fields=["is_used"])
        return True


# ═══════════════════════════════════════════════════════════════════════════
# Organization
# ═══════════════════════════════════════════════════════════════════════════

class Organization(models.Model):
    """
    A workspace that a Manager creates after registering.

    All application data (Projects, Clients, Staff) will eventually be
    scoped under an Organization so that data from different organizations
    never leaks across boundaries.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    description = models.TextField(blank=True)

    # Optional contact / profile information.
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    website = models.URLField(blank=True)

    logo = models.ImageField(
        upload_to="organizations/logos/",
        blank=True,
        null=True,
    )

    # The user who created this organization. PROTECT prevents accidental
    # deletion of the organization when the owner account is deleted.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_organizations",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"

    def __str__(self):
        return self.name

    # ------------------------------------------------------------------ #
    # Slug helpers                                                         #
    # ------------------------------------------------------------------ #

    @classmethod
    def _unique_slug(cls, base: str) -> str:
        """
        Generate a slug from `base` that does not already exist in the table.
        Appends a numeric suffix when there is a collision.
        """
        slug = slugify(base)[:200]  # leave room for suffix within max_length
        candidate = slug
        counter = 1
        while cls.objects.filter(slug=candidate).exists():
            candidate = f"{slug}-{counter}"
            counter += 1
        return candidate

    def save(self, *args, **kwargs):
        # Auto-generate slug on first save only; allow manual override.
        if not self.slug:
            self.slug = self._unique_slug(self.name)
        super().save(*args, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# OrganizationMembership
# ═══════════════════════════════════════════════════════════════════════════

class OrganizationMembership(models.Model):
    """
    Ties a User to an Organization with an organization-level role.

    This is the authoritative source for organization-level access control.
    User.role is kept for compatibility with existing code, but
    OrganizationMembership.role drives all organization-scoped authorization.

    Roles mirror the global User.Role choices so that permission helpers
    remain consistent across both access-control layers.
    """

    class Role(models.TextChoices):
        MANAGER = "MANAGER", "Manager"
        STAFF = "STAFF", "Staff"
        CLIENT = "CLIENT", "Client"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
    )

    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Organization Membership"
        verbose_name_plural = "Organization Memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization"],
                name="unique_user_organization_membership",
            )
        ]

    def __str__(self):
        return f"{self.user.username} → {self.organization.name} ({self.role})"

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import OTPCode, Organization, OrganizationMembership, User


# ─────────────────────────────────────────────────────────────────────────────
# User
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Extends Django's built-in UserAdmin to expose the application `role`."""

    list_display = (
        "username", "email", "first_name", "last_name",
        "role", "is_active", "is_staff", "date_joined",
    )
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-date_joined",)

    # Append role to the standard change-form fieldsets.
    fieldsets = UserAdmin.fieldsets + (
        ("ClientSpace Role", {"fields": ("role",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("ClientSpace Role", {"fields": ("role",)}),
    )


# ─────────────────────────────────────────────────────────────────────────────
# OTPCode
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ("__str__", "purpose", "is_used", "is_expired", "created_at")
    list_filter = ("purpose", "is_used")
    readonly_fields = ("code", "created_at")
    search_fields = ("user__username", "pending_email")
    ordering = ("-created_at",)


# ─────────────────────────────────────────────────────────────────────────────
# Organization
# ─────────────────────────────────────────────────────────────────────────────

class OrganizationMembershipInline(admin.TabularInline):
    """Show memberships directly on the Organization page for convenience."""
    model = OrganizationMembership
    extra = 0
    readonly_fields = ("joined_at",)
    fields = ("user", "role", "joined_at")


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "email", "created_by", "created_at")
    list_filter = ("created_at",)
    search_fields = ("name", "slug", "email", "created_by__username")
    readonly_fields = ("slug", "created_at", "updated_at")
    ordering = ("name",)
    inlines = [OrganizationMembershipInline]

    fieldsets = (
        (None, {
            "fields": ("name", "slug", "description", "logo"),
        }),
        ("Contact", {
            "fields": ("email", "phone", "address", "website"),
            "classes": ("collapse",),
        }),
        ("Ownership", {
            "fields": ("created_by", "created_at", "updated_at"),
        }),
    )


# ─────────────────────────────────────────────────────────────────────────────
# OrganizationMembership
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "joined_at")
    list_filter = ("role", "organization")
    search_fields = ("user__username", "user__email", "organization__name")
    readonly_fields = ("joined_at",)
    ordering = ("organization", "role", "user")

from django.contrib import admin

from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display   = ("name", "organization", "client", "status", "priority", "created_by", "deadline", "created_at")
    list_filter    = ("status", "priority")
    search_fields  = (
        "name",
        "client__username",
        "client__email",
        "created_by__username",
        "created_by__email",
    )
    readonly_fields = ("created_at", "updated_at")
    ordering       = ("-created_at",)

    fieldsets = (
        ("Project", {
            "fields": ("name", "description", "organization", "client"),
        }),
        ("Classification", {
            "fields": ("status", "priority"),
        }),
        ("Timeline & Budget", {
            "fields": ("start_date", "deadline", "budget"),
        }),
        ("Metadata", {
            "fields": ("created_by", "created_at", "updated_at"),
        }),
    )

from django.contrib import admin

from .models import Project, Task
from staff.models import StaffAssignment


class StaffAssignmentInline(admin.TabularInline):
    """Read-only inline showing staff assignments on the Project admin page."""
    model = StaffAssignment
    extra = 0
    fields = ("staff", "assigned_by", "assigned_at", "is_active", "completed_at")
    readonly_fields = ("assigned_by", "assigned_at", "completed_at")
    ordering = ("-assigned_at",)
    show_change_link = True
    verbose_name = "Staff Assignment"
    verbose_name_plural = "Staff Assignments"


class TaskInline(admin.TabularInline):
    """Inline showing tasks on the Project admin page."""
    model = Task
    extra = 0
    fields = ("title", "assigned_to", "status", "priority", "due_date")
    readonly_fields = ("created_by",)
    ordering = ("due_date", "title")
    show_change_link = True
    verbose_name = "Task"
    verbose_name_plural = "Tasks"


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
    inlines        = [StaffAssignmentInline, TaskInline]

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


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display   = ("title", "project", "assigned_to", "status", "priority", "due_date", "created_by", "created_at")
    list_filter    = ("status", "priority")
    search_fields  = (
        "title",
        "project__name",
        "assigned_to__username",
        "assigned_to__first_name",
        "assigned_to__last_name",
        "created_by__username",
    )
    readonly_fields = ("created_at", "updated_at", "created_by")
    ordering        = ("-created_at",)

    fieldsets = (
        ("Task", {
            "fields": ("title", "description", "project", "assigned_to"),
        }),
        ("Classification", {
            "fields": ("status", "priority", "due_date"),
        }),
        ("Metadata", {
            "fields": ("created_by", "created_at", "updated_at"),
        }),
    )

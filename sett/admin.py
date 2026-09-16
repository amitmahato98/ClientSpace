from django.contrib import admin
from .models import Workspace


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "role", "currency", "updated_at")
    list_filter = ("currency", "created_at", "updated_at")
    search_fields = ("name", "user__username", "user__email", "role")

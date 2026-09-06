from django.contrib import admin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display   = ("recipient", "actor", "is_read", "created_at", "short_message", "link")
    list_filter    = ("is_read", "created_at")
    search_fields  = (
        "recipient__username",
        "recipient__email",
        "actor__username",
        "message",
    )
    readonly_fields = ("created_at",)
    ordering        = ("-created_at",)

    @admin.display(description="Message")
    def short_message(self, obj):
        return obj.message[:80] + ("…" if len(obj.message) > 80 else "")

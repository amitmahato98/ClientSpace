from django.contrib import admin
from .models import Notification, NotificationSetting


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display   = ("recipient", "notification_type", "actor", "is_read", "created_at", "short_message", "link")
    list_filter    = ("notification_type", "is_read", "created_at")
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


@admin.register(NotificationSetting)
class NotificationSettingAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "payment_received",
        "deadline_reminder",
        "overdue_alert",
        "client_portal_viewed",
        "team_member_joined",
        "weekly_summary",
        "account_activity",
        "updated_at",
    )
    search_fields = ("user__username", "user__email")


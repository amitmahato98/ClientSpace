from django.contrib import admin

from .models import PaymentRequest


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display  = (
        "title", "project", "client", "amount", "status",
        "due_date", "created_by", "created_at",
    )
    list_filter   = ("status", "created_at", "due_date")
    search_fields = ("title", "project__name", "client__username", "client__email")
    ordering      = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("project", "client", "created_by")

    fieldsets = (
        (None, {
            "fields": ("project", "client", "created_by", "title", "description"),
        }),
        ("Financial", {
            "fields": ("amount", "status", "due_date"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

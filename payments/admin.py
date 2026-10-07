from django.contrib import admin

from .models import PaymentRequest, PaymentTransaction


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


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "pk", "payment_request", "project", "client", "amount",
        "payment_method", "status", "gateway_transaction_id", "paid_at", "created_at",
    )
    list_filter  = ("status", "payment_method", "created_at")
    search_fields = (
        "payment_request__title", "project__name",
        "client__username", "client__email",
        "gateway_transaction_id",
    )
    ordering      = ("-created_at",)
    readonly_fields = (
        "payment_request", "project", "client", "amount",
        "payment_method", "gateway_transaction_id",
        "paid_at", "created_at", "updated_at",
    )
    list_select_related = ("payment_request", "project", "client")

    fieldsets = (
        ("Transaction", {
            "fields": (
                "payment_request", "project", "client",
                "amount", "payment_method", "gateway_transaction_id",
            ),
        }),
        ("Status", {
            "fields": ("status", "failure_reason"),
        }),
        ("Timestamps", {
            "fields": ("paid_at", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        # Transactions are created only by the service layer, never manually.
        return False

    def has_change_permission(self, request, obj=None):
        # Status changes must go through the service layer, not the admin UI.
        return False

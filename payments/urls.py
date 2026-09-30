from django.urls import path
from payments import views

app_name = "payments"

urlpatterns = [
    # ── Manager: overview of all payment requests across org ─────────────────
    path("", views.payment_view, name="payment_view"),

    # ── Manager: payment requests for a specific project ─────────────────────
    path("project/<int:project_pk>/", views.project_payments, name="project_payments"),

    # ── Manager: create a new payment request for a project ──────────────────
    path("project/<int:project_pk>/create/", views.create_payment_request, name="create_payment_request"),

    # ── Manager: mark a payment request as paid / cancelled / overdue ────────
    path("<int:pk>/status/", views.update_payment_status, name="update_payment_status"),

    # ── Client: view their own payment requests ───────────────────────────────
    path("my/", views.client_payments, name="client_payments"),
]

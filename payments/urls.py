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

    # ── Phase 3: Client — initiate a payment transaction ─────────────────────
    # GET  → confirmation page showing PR details before committing
    # POST → creates the PaymentTransaction (INITIATED), redirects to simulate
    path("initiate/<int:pr_pk>/", views.initiate_payment, name="initiate_payment"),

    # ── Phase 3: Simulation — confirm SUCCESS or FAILED (DEBUG only) ─────────
    # POST with outcome=success|failed.
    # Guarded server-side: returns 404 when DEBUG=False.
    path("simulate/<int:txn_pk>/", views.simulate_payment_result, name="simulate_payment_result"),

    # ── Phase 3: Payment result page ─────────────────────────────────────────
    # Shown after simulate completes; also reachable from history.
    path("result/<int:txn_pk>/", views.payment_result, name="payment_result"),

    # ── Phase 3: Client — full transaction history ────────────────────────────
    path("history/", views.transaction_history, name="transaction_history"),
]

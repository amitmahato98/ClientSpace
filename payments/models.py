"""
payments/models.py
──────────────────
Phase 2: PaymentRequest  — a billing milestone created by a Manager.
Phase 3: PaymentTransaction — an actual payment attempt by a Client.

Separation of concerns
──────────────────────
PaymentRequest  = "Client needs to pay NPR 20,000."
PaymentTransaction = "Client attempted / completed payment of NPR 20,000."

A PaymentRequest is only marked PAID when a PaymentTransaction with
status=SUCCESS is recorded against it (via the service layer in
payments/service.py).  No manual marking by the client is ever allowed.

All amounts: Decimal, NPR only.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class PaymentRequest(models.Model):
    """
    A payment milestone that a Manager creates for a Client on a Project.

    Lifecycle
    ─────────
    PENDING   → the default state when first created.
    PAID      → the Manager has confirmed payment was received (Phase 3 will
                integrate Khalti; for now Managers mark it manually).
    OVERDUE   → set by the Manager when a PENDING request passes its due date
                and still hasn't been paid.
    CANCELLED → the Manager has cancelled the request (e.g. scope change).

    Design notes
    ────────────
    • `project.client` already points at the CLIENT User, so we look up the
      client via `payment_request.project.client` — no redundant FK needed.
    • `created_by` is always a Manager; enforced at the view layer.
    • `due_date` is optional — not every request has a hard deadline.
    • Amounts are DecimalField (max_digits=12, decimal_places=2) to match
      Project.budget and be consistent with clients.Payment.
    """

    class Status(models.TextChoices):
        PENDING   = "PENDING",   "Pending"
        PAID      = "PAID",      "Paid"
        OVERDUE   = "OVERDUE",   "Overdue"
        CANCELLED = "CANCELLED", "Cancelled"

    # ── Core relationships ────────────────────────────────────────────────────

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="payment_requests",
        help_text="The project this payment request belongs to.",
    )

    # Convenience FK so we can filter payment requests by client directly
    # without always joining through Project.  Mirrors project.client so
    # must be set to project.client at creation time (enforced in views).
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_requests",
        limit_choices_to={"role": "CLIENT"},
        help_text="The client who is expected to pay.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payment_requests",
        help_text="Manager who created this payment request.",
    )

    # ── Financial fields ──────────────────────────────────────────────────────

    title = models.CharField(
        max_length=200,
        help_text='Short description, e.g. "Initial Payment", "Milestone 1".',
    )

    description = models.TextField(
        blank=True,
        help_text="Optional longer description for the client.",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Amount due in NPR.",
    )

    # ── Status ────────────────────────────────────────────────────────────────

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    due_date = models.DateField(
        null=True,
        blank=True,
        help_text="Optional deadline for this payment.",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Payment Request"
        verbose_name_plural = "Payment Requests"

    def __str__(self):
        client_name = self.client.username if self.client else "No client"
        return f"{self.title} — {self.project.name} ({client_name}) — NPR {self.amount}"

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def is_pending(self):
        return self.status == self.Status.PENDING

    @property
    def is_paid(self):
        return self.status == self.Status.PAID

    @property
    def status_css_class(self):
        """Tailwind badge CSS classes matching the existing UI colour scheme."""
        return {
            self.Status.PENDING:   "bg-[#fef7e0] text-[#b06000]",
            self.Status.PAID:      "bg-[#e6f4ea] text-[#137333]",
            self.Status.OVERDUE:   "bg-[#fce8e6] text-[#c5221f]",
            self.Status.CANCELLED: "bg-[#f3f4f6] text-[#6b7280]",
        }.get(self.status, "bg-gray-100 text-gray-600")

    @property
    def status_icon(self):
        return {
            self.Status.PENDING:   "fa-clock",
            self.Status.PAID:      "fa-check-circle",
            self.Status.OVERDUE:   "fa-exclamation-circle",
            self.Status.CANCELLED: "fa-times-circle",
        }.get(self.status, "fa-circle")


# ═══════════════════════════════════════════════════════════════════════════
# PaymentTransaction  — Phase 3
# ═══════════════════════════════════════════════════════════════════════════

class PaymentTransaction(models.Model):
    """
    Records a single payment attempt or completed transaction for a
    PaymentRequest.

    Lifecycle
    ─────────
    INITIATED → created when the client clicks "Pay Now" and confirms.
                The PaymentRequest remains PENDING at this point.
    SUCCESS   → set by the service layer after the gateway (or, in Phase 3,
                the simulation endpoint) confirms a successful payment.
                The related PaymentRequest is automatically set to PAID.
    FAILED    → set when the payment attempt is rejected or times out.
                The PaymentRequest remains PENDING so the client can retry.
    REFUNDED  → reserved for a future refund workflow (Phase 4+).
                The related PaymentRequest is reset to PENDING.

    Design for future Khalti integration
    ──────────────────────────────────────
    • `payment_method` uses TextChoices — adding KHALTI or ESEWA later is a
      one-line change with a migration; no architectural rework needed.
    • `gateway_transaction_id` will hold Khalti's pidx / transaction ID once
      real integration ships.  It is optional and nullable so Phase 3 works
      without it.
    • The service layer (payments/service.py) is the ONLY code that writes
      to this model and the only code that transitions PaymentRequest status.
      Views never write directly — they call service functions.

    Security invariants (enforced in views + service, not just templates)
    ──────────────────────────────────────────────────────────────────────
    • `amount` is always copied from `payment_request.amount` server-side.
      It is never read from POST data.
    • `client` is always copied from `payment_request.client` server-side.
    • `project` is always copied from `payment_request.project` server-side.
    • `status` can only be advanced by the service layer, never by the client.
    """

    class Status(models.TextChoices):
        INITIATED = "INITIATED", "Initiated"
        SUCCESS   = "SUCCESS",   "Success"
        FAILED    = "FAILED",    "Failed"
        REFUNDED  = "REFUNDED",  "Refunded"

    class PaymentMethod(models.TextChoices):
        SIMULATION = "SIMULATION", "Simulation (Dev/Test)"
        KHALTI     = "KHALTI",     "Khalti"
        ESEWA      = "ESEWA",      "eSewa"
        BANK       = "BANK",       "Bank Transfer"
        OTHER      = "OTHER",      "Other"

    # ── Core relationships ────────────────────────────────────────────────────

    payment_request = models.ForeignKey(
        PaymentRequest,
        on_delete=models.CASCADE,
        related_name="transactions",
        help_text="The PaymentRequest this transaction is for.",
    )

    # Denormalised for efficient querying — always mirrors
    # payment_request.project and payment_request.client.
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="payment_transactions",
        help_text="Denormalised from payment_request.project.",
    )

    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_transactions",
        limit_choices_to={"role": "CLIENT"},
        help_text="Denormalised from payment_request.client.",
    )

    # ── Financial ─────────────────────────────────────────────────────────────

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Amount in NPR — always copied server-side from the PaymentRequest.",
    )

    # ── Gateway / method ──────────────────────────────────────────────────────

    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.SIMULATION,
        help_text="Payment method used for this transaction.",
    )

    # Will hold Khalti pidx / eSewa ref / bank ref in future phases.
    gateway_transaction_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Gateway-assigned transaction/reference ID. "
            "Empty for SIMULATION; populated by real gateway in Phase 4+."
        ),
    )

    # ── Status ────────────────────────────────────────────────────────────────

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.INITIATED,
    )

    # Reason for failure — stored for debugging; never shown to clients.
    failure_reason = models.TextField(
        blank=True,
        default="",
        help_text="Internal: reason for FAILED status. Never exposed to clients.",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Set explicitly by the service layer on SUCCESS, not auto_now.
    paid_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the transaction was confirmed successful.",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Payment Transaction"
        verbose_name_plural = "Payment Transactions"
        indexes = [
            # Fast lookup: all transactions for a client across all projects.
            models.Index(fields=["client", "-created_at"]),
            # Fast lookup: all transactions for a specific payment request.
            models.Index(fields=["payment_request", "status"]),
        ]

    def __str__(self):
        return (
            f"Txn #{self.pk} — {self.get_payment_method_display()} — "
            f"NPR {self.amount} — {self.get_status_display()} "
            f"({self.payment_request.title})"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def is_success(self):
        return self.status == self.Status.SUCCESS

    @property
    def is_failed(self):
        return self.status == self.Status.FAILED

    @property
    def status_css_class(self):
        return {
            self.Status.INITIATED: "bg-[#e8f0fe] text-[#1a73e8]",
            self.Status.SUCCESS:   "bg-[#e6f4ea] text-[#137333]",
            self.Status.FAILED:    "bg-[#fce8e6] text-[#c5221f]",
            self.Status.REFUNDED:  "bg-[#f3f4f6] text-[#6b7280]",
        }.get(self.status, "bg-gray-100 text-gray-600")

    @property
    def status_icon(self):
        return {
            self.Status.INITIATED: "fa-spinner",
            self.Status.SUCCESS:   "fa-check-circle",
            self.Status.FAILED:    "fa-times-circle",
            self.Status.REFUNDED:  "fa-undo",
        }.get(self.status, "fa-circle")

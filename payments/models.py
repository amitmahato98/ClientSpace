"""
payments/models.py
──────────────────
Payment Request model for ClientSpace Phase 2.

A PaymentRequest represents a specific amount that a Client is expected to pay
for work on a Project.  It is created by a Manager (either automatically when
a project is created, or manually for later milestones).

The Client can view their own payment requests but cannot create, edit, or
mark them as paid — those operations are Manager-only.

All monetary amounts are stored as Decimal (never float) in NPR.
ClientSpace is NPR-only; no separate currency field is needed.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models


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

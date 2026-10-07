"""
payments/service.py
───────────────────
Service layer for the PaymentTransaction lifecycle.

Phase 2  — PaymentRequest creation (in projects/views.py)
Phase 3  — Transaction lifecycle: initiate, record_success, record_failure
Phase 4  — Financial summary helpers, over-request guard, client email

PUBLIC API
──────────
  initiate_payment(payment_request, client, method)   → PaymentTransaction
  record_success(txn, gateway_transaction_id="")       → PaymentTransaction
  record_failure(txn, reason="")                       → PaymentTransaction
  get_paid_amount_for_project(project)                 → Decimal
  get_paid_amount_for_client(client)                   → Decimal
  get_pending_amount_for_project(project)              → Decimal   [Phase 4]
  get_available_amount_for_project(project)            → Decimal   [Phase 4]
  get_project_financial_summary(project)               → dict      [Phase 4]
  send_payment_request_email(pr, login_url)            → None      [Phase 4]

BALANCE CALCULATION RULES (Phase 4)
─────────────────────────────────────
  paid_amount      = SUM of PaymentTransaction.amount where status=SUCCESS
  pending_amount   = SUM of PaymentRequest.amount where status=PENDING
  available_amount = project.budget - paid_amount - pending_amount
                     (clamped to 0, never negative)

  A new payment request of amount X is valid iff:
      X > 0  AND  X <= available_amount

  This prevents two failure modes:
    1. Requesting more than the budget in a single request.
    2. Combined pending + paid requests exceeding the budget
       even when each individual request looks fine.

CONCURRENCY SAFETY
──────────────────
  create_payment_request (view) uses select_for_update() on the Project
  row inside transaction.atomic() before computing available_amount.
  This serialises concurrent requests for the same project so the
  available_amount cannot be over-committed.

FUTURE KHALTI HOOK POINTS
──────────────────────────
  • initiate_payment()  → call Khalti initiate API, store pidx in txn,
                          redirect client to Khalti payment page.
  • A new `handle_khalti_callback(pidx, status, …)` function will call
    record_success() or record_failure() after verifying the callback.
"""

import logging
import uuid
from decimal import Decimal

from django.conf import settings as django_settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import PaymentRequest, PaymentTransaction

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public exceptions
# ─────────────────────────────────────────────────────────────────────────────

class PaymentError(Exception):
    """Base exception for all payment service errors."""


class PaymentAlreadyPaidError(PaymentError):
    """Raised when trying to initiate a payment for an already-PAID request."""


class PaymentCancelledError(PaymentError):
    """Raised when trying to initiate a payment for a CANCELLED request."""


class InvalidTransactionError(PaymentError):
    """Raised when record_success/record_failure is called on a bad txn."""


class OverRequestError(PaymentError):
    """Raised when a new PaymentRequest would exceed the available balance."""


# ─────────────────────────────────────────────────────────────────────────────
# initiate_payment
# ─────────────────────────────────────────────────────────────────────────────

def initiate_payment(
    payment_request: PaymentRequest,
    client,
    method: str = PaymentTransaction.PaymentMethod.SIMULATION,
) -> PaymentTransaction:
    """
    Create a new PaymentTransaction in INITIATED state for the given request.

    Guards
    ──────
    • Raises PaymentAlreadyPaidError if the request is already PAID.
    • Raises PaymentCancelledError if the request is CANCELLED.
    • Verifies client == payment_request.client (server-side ownership check).

    The amount is always copied from payment_request.amount — never from
    user input.

    Returns the created PaymentTransaction (status=INITIATED).
    """
    if client.pk != payment_request.client_id:
        raise InvalidTransactionError(
            f"Client {client.pk} does not own PaymentRequest {payment_request.pk}."
        )

    if payment_request.status == PaymentRequest.Status.PAID:
        raise PaymentAlreadyPaidError(
            f'PaymentRequest "{payment_request.title}" is already PAID.'
        )

    if payment_request.status == PaymentRequest.Status.CANCELLED:
        raise PaymentCancelledError(
            f'PaymentRequest "{payment_request.title}" has been cancelled.'
        )

    txn = PaymentTransaction.objects.create(
        payment_request   = payment_request,
        project           = payment_request.project,   # always server-side
        client            = payment_request.client,    # always server-side
        amount            = payment_request.amount,    # always server-side
        payment_method    = method,
        status            = PaymentTransaction.Status.INITIATED,
    )

    logger.info(
        "Payment INITIATED: txn #%d  PR #%d  client=%s  amount=NPR %s  method=%s",
        txn.pk, payment_request.pk, client.username, txn.amount, method,
    )
    return txn


# ─────────────────────────────────────────────────────────────────────────────
# record_success
# ─────────────────────────────────────────────────────────────────────────────

def record_success(
    txn: PaymentTransaction,
    gateway_transaction_id: str = "",
) -> PaymentTransaction:
    """
    Mark a PaymentTransaction as SUCCESS and update the related
    PaymentRequest to PAID.

    Both writes happen inside a single atomic transaction so they
    are always consistent.

    Raises InvalidTransactionError if the transaction is not in INITIATED
    state (idempotency guard — prevents double-processing).
    """
    if txn.status != PaymentTransaction.Status.INITIATED:
        raise InvalidTransactionError(
            f"Cannot mark txn #{txn.pk} as SUCCESS — current status is {txn.status}."
        )

    now = timezone.now()

    with transaction.atomic():
        txn.status                 = PaymentTransaction.Status.SUCCESS
        txn.paid_at                = now
        txn.gateway_transaction_id = gateway_transaction_id or _generate_internal_ref(txn)
        txn.save(update_fields=["status", "paid_at", "gateway_transaction_id", "updated_at"])

        # Mark the related PaymentRequest as PAID.
        PaymentRequest.objects.filter(pk=txn.payment_request_id).update(
            status     = PaymentRequest.Status.PAID,
            updated_at = now,
        )

    logger.info(
        "Payment SUCCESS: txn #%d  PR #%d  client=%s  amount=NPR %s  ref=%s",
        txn.pk,
        txn.payment_request_id,
        txn.client.username,
        txn.amount,
        txn.gateway_transaction_id,
    )
    return txn


# ─────────────────────────────────────────────────────────────────────────────
# record_failure
# ─────────────────────────────────────────────────────────────────────────────

def record_failure(
    txn: PaymentTransaction,
    reason: str = "Payment failed.",
) -> PaymentTransaction:
    """
    Mark a PaymentTransaction as FAILED.

    The related PaymentRequest is intentionally NOT changed — it stays
    PENDING so the client can retry.

    Raises InvalidTransactionError if the transaction is not INITIATED.
    """
    if txn.status != PaymentTransaction.Status.INITIATED:
        raise InvalidTransactionError(
            f"Cannot mark txn #{txn.pk} as FAILED — current status is {txn.status}."
        )

    txn.status         = PaymentTransaction.Status.FAILED
    txn.failure_reason = reason
    txn.save(update_fields=["status", "failure_reason", "updated_at"])

    logger.warning(
        "Payment FAILED: txn #%d  PR #%d  client=%s  reason=%s",
        txn.pk, txn.payment_request_id, txn.client.username, reason,
    )
    return txn


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 — Financial calculation helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_paid_amount_for_project(project) -> Decimal:
    """
    Total successfully paid amount for a project.

    Source: SUM(PaymentTransaction.amount) WHERE status=SUCCESS.
    This is the ONLY authoritative paid-amount source.
    Returns Decimal("0.00") if no successful transactions exist.
    """
    result = PaymentTransaction.objects.filter(
        project=project,
        status=PaymentTransaction.Status.SUCCESS,
    ).aggregate(total=Sum("amount"))["total"]
    return result or Decimal("0.00")


def get_paid_amount_for_client(client) -> Decimal:
    """
    Total paid across ALL projects for a given client.
    Used for the grand-total summary on the client payments page.
    """
    result = PaymentTransaction.objects.filter(
        client=client,
        status=PaymentTransaction.Status.SUCCESS,
    ).aggregate(total=Sum("amount"))["total"]
    return result or Decimal("0.00")


def get_pending_amount_for_project(project) -> Decimal:
    """
    Sum of all PENDING (and OVERDUE) PaymentRequest amounts for a project.

    These are amounts the client has been asked to pay but has not yet paid.
    They count against the available balance so Managers cannot over-request.

    PENDING + OVERDUE both consume "promised" budget.
    PAID requests are already settled.
    CANCELLED requests are excluded (they no longer consume budget).
    """
    result = PaymentRequest.objects.filter(
        project=project,
        status__in=[PaymentRequest.Status.PENDING, PaymentRequest.Status.OVERDUE],
    ).aggregate(total=Sum("amount"))["total"]
    return result or Decimal("0.00")


def get_available_amount_for_project(project) -> Decimal:
    """
    How much budget is still available for new payment requests.

    Formula
    ───────
    available = project.budget
                - paid_amount        (confirmed by successful transactions)
                - pending_amount     (already requested but not yet paid)

    Clamped to max(0, …) so it is never negative.

    This is the ceiling for any new PaymentRequest amount.  A Manager
    cannot create a request that exceeds this value.
    """
    paid    = get_paid_amount_for_project(project)
    pending = get_pending_amount_for_project(project)
    budget  = project.budget or Decimal("0.00")
    available = budget - paid - pending
    return max(Decimal("0.00"), available)


def get_project_financial_summary(project) -> dict:
    """
    Return a dict with all financial figures for a project.

    Keys
    ────
    budget          — Project.budget (Decimal)
    paid            — sum of successful transactions (Decimal)
    pending         — sum of PENDING/OVERDUE PR amounts (Decimal)
    available       — budget - paid - pending, clamped ≥ 0 (Decimal)
    is_fully_paid   — True when budget > 0 and available == 0 and pending == 0
                      (i.e. all budget has been paid, nothing outstanding)

    is_fully_paid is True only when:
      • budget > 0
      • paid >= budget  (all money collected)
      • pending == 0    (no open requests that haven't settled yet)

    Used by both the manager project_payments view and the client
    client_payments view to display consistent financial information.
    """
    budget    = project.budget or Decimal("0.00")
    paid      = get_paid_amount_for_project(project)
    pending   = get_pending_amount_for_project(project)
    available = max(Decimal("0.00"), budget - paid - pending)

    is_fully_paid = (
        budget > Decimal("0.00")
        and paid >= budget
        and pending == Decimal("0.00")
    )

    return {
        "budget":        budget,
        "paid":          paid,
        "pending":       pending,
        "available":     available,
        "is_fully_paid": is_fully_paid,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 — Client email for new payment requests
# ─────────────────────────────────────────────────────────────────────────────

def send_payment_request_email(pr: PaymentRequest, login_url: str) -> None:
    """
    Send a professional notification email to the client when a Manager
    creates a new PaymentRequest.

    Design mirrors the existing pattern in projects/views.py:
    • Uses DEFAULT_FROM_EMAIL or falls back to EMAIL_HOST_USER.
    • Called via transaction.on_commit() so the email only fires after
      the PaymentRequest row is safely committed to the database.
    • Errors are caught and logged — they do NOT propagate so they cannot
      corrupt the payment request that was already saved.

    Parameters
    ──────────
    pr          — the newly created PaymentRequest (must be saved already)
    login_url   — absolute URL to the login page (built by the view with
                  request.build_absolute_uri so it is host-aware)
    """
    try:
        client = pr.client
        project = pr.project
        summary = get_project_financial_summary(project)

        from_addr = (
            django_settings.DEFAULT_FROM_EMAIL
            or django_settings.EMAIL_HOST_USER
        )

        client_name = (
            client.get_full_name().strip()
            or client.display_name
            or client.username
        )

        subject = f"Payment Request for {project.name} — ClientSpace"

        body = (
            f"Hello {client_name},\n\n"
            f"A new payment request has been created for your project "
            f'"{project.name}".\n\n'
            f"─────────────────────────────\n"
            f"Payment Request Details\n"
            f"─────────────────────────────\n"
            f"  Title:              {pr.title}\n"
        )

        if pr.description:
            body += f"  Description:        {pr.description}\n"

        body += (
            f"  Amount Requested:   NPR {pr.amount:,.2f}\n"
        )

        if pr.due_date:
            body += f"  Due Date:           {pr.due_date.strftime('%B %d, %Y')}\n"

        body += (
            f"\n"
            f"─────────────────────────────\n"
            f"Project Financial Summary\n"
            f"─────────────────────────────\n"
            f"  Project Budget:     NPR {summary['budget']:,.2f}\n"
            f"  Amount Paid:        NPR {summary['paid']:,.2f}\n"
            f"  Pending Requests:   NPR {summary['pending']:,.2f}\n"
            f"  Remaining Balance:  NPR {summary['available']:,.2f}\n"
            f"\n"
            f"─────────────────────────────\n"
            f"\n"
            f"Please log in to ClientSpace to review the payment request "
            f"and complete the payment.\n\n"
            f"  {login_url}\n\n"
            f"If you have any questions, please contact your project manager.\n\n"
            f"Regards,\n"
            f"ClientSpace Team\n"
        )

        send_mail(
            subject=subject,
            message=body,
            from_email=from_addr,
            recipient_list=[client.email],
            fail_silently=False,
        )

        logger.info(
            "Payment request email sent to %s for PR #%d (%s) on project %s",
            client.email, pr.pk, pr.title, project.name,
        )

    except Exception as exc:
        # Log but never re-raise — email failure must not roll back
        # a payment request that was already committed.
        logger.error(
            "Failed to send payment request email for PR #%d to %s: %s",
            pr.pk if pr.pk else "?",
            getattr(pr, "client", {}) and getattr(pr.client, "email", "?"),
            exc,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _generate_internal_ref(txn: PaymentTransaction) -> str:
    """
    Generate a deterministic internal reference for simulation transactions.
    Format: SIM-<project_pk>-<pr_pk>-<txn_pk>-<uuid4 short>
    """
    short_uuid = uuid.uuid4().hex[:8].upper()
    return f"SIM-{txn.project_id}-{txn.payment_request_id}-{txn.pk}-{short_uuid}"

"""
payments/service.py
───────────────────
Service layer for the PaymentTransaction lifecycle (Phase 3).

WHY A SERVICE LAYER?
─────────────────────
Views must never directly write PaymentTransaction rows or change
PaymentRequest.status.  Centralising all mutation here means:

  1. The logic is tested independently of HTTP.
  2. When Khalti is integrated (Phase 4) only THIS file changes —
     views, templates, and the URL structure stay the same.
  3. No scattered `payment_request.status = "PAID"` littered across views.

PUBLIC API
──────────
  initiate_payment(payment_request, client, method)  → PaymentTransaction
  record_success(txn, gateway_transaction_id="")      → PaymentTransaction
  record_failure(txn, reason="")                      → PaymentTransaction

FUTURE KHALTI HOOK POINTS
──────────────────────────
  • initiate_payment()  → call Khalti initiate API, store pidx in txn,
                          redirect client to Khalti payment page.
  • A new `handle_khalti_callback(pidx, status, …)` function will call
    record_success() or record_failure() after verifying the callback.

SIMULATION (Phase 3 only)
──────────────────────────
  The `simulate_result` view calls record_success() / record_failure()
  directly.  It is guarded by `settings.DEBUG` so it can never be called
  in production without DEBUG=True.
"""

import logging
import uuid

from django.db import transaction
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

    • `gateway_transaction_id` is the identifier returned by the real payment
      gateway (e.g. Khalti pidx).  In Phase 3 simulation it is left blank
      or can be set to a generated reference.
    • `paid_at` is recorded at the moment of confirmation.
    • The PaymentRequest.status is set to PAID only here — never in views.

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

    `reason` is stored internally for debugging; it is never surfaced
    to the client in templates.

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
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _generate_internal_ref(txn: PaymentTransaction) -> str:
    """
    Generate a deterministic internal reference for simulation transactions.
    Format: SIM-<project_pk>-<pr_pk>-<txn_pk>-<uuid4 short>

    This is NOT a real gateway reference — it exists purely so every
    successful simulation has a non-empty gateway_transaction_id that looks
    meaningful in the history table.
    """
    short_uuid = uuid.uuid4().hex[:8].upper()
    return f"SIM-{txn.project_id}-{txn.payment_request_id}-{txn.pk}-{short_uuid}"


def get_paid_amount_for_project(project) -> object:
    """
    Calculate the total successfully paid amount for a project by summing
    PaymentTransaction.amount where status=SUCCESS.

    This is the ONLY authoritative source for "how much has been paid".
    Views and templates must call this instead of summing PaymentRequest
    statuses manually.

    Returns a Decimal (0.00 if no successful transactions exist).
    """
    from decimal import Decimal
    from django.db.models import Sum, Q

    result = PaymentTransaction.objects.filter(
        project=project,
        status=PaymentTransaction.Status.SUCCESS,
    ).aggregate(total=Sum("amount"))["total"]
    return result or Decimal("0.00")


def get_paid_amount_for_client(client) -> object:
    """
    Total paid across ALL projects for a given client.
    Used for the grand-total summary on the client payments page.
    """
    from decimal import Decimal
    from django.db.models import Sum

    result = PaymentTransaction.objects.filter(
        client=client,
        status=PaymentTransaction.Status.SUCCESS,
    ).aggregate(total=Sum("amount"))["total"]
    return result or Decimal("0.00")

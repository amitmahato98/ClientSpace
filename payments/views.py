"""
payments/views.py
─────────────────
Phase 2 views (unchanged structure, client_payments upgraded to txn-based totals):
  client_payments          — CLIENT; transaction-based paid totals
  payment_view             — MANAGER/STAFF; org-scoped overview
  project_payments         — MANAGER/STAFF; single project
  create_payment_request   — MANAGER; POST-only
  update_payment_status    — MANAGER; POST-only

Phase 3 views (new):
  initiate_payment         — CLIENT; GET=confirm page, POST=create INITIATED txn
  simulate_payment_result  — CLIENT; POST-only, DEBUG=True only
  payment_result           — CLIENT; read-only result page
  transaction_history      — CLIENT; full transaction history

Security model
──────────────
• All sensitive values (amount, project, client) are always derived
  server-side from DB records — never from POST data.
• simulate_payment_result returns 404 when DEBUG=False, making it
  impossible to call in production.
• All client views filter strictly by client=request.user.
• All manager views filter by project__organization=manager_org.
• The service layer is the ONLY code that writes PaymentTransaction rows
  or transitions PaymentRequest.status.
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.decorators import manager_required, staff_or_above
from accounts.views import get_user_organization
from projects.models import Project

from .forms import PaymentRequestForm, PaymentStatusForm
from .models import PaymentRequest, PaymentTransaction
from . import service

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CLIENT VIEW — /payments/my/   (Phase 2, upgraded to txn-based paid totals)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def client_payments(request):
    """
    Show all PaymentRequests for the logged-in CLIENT with transaction-based
    paid totals.

    Phase 3 upgrade:
      grand_paid is now calculated from successful PaymentTransactions, not
      from PaymentRequest.status == PAID.  This is the authoritative source.
    """
    payment_requests = (
        PaymentRequest.objects
        .select_related("project", "project__organization", "created_by")
        .filter(client=request.user)
        .order_by("project__name", "created_at")
    )

    # Transaction-based paid amount (authoritative for Phase 3+)
    txn_paid_total = service.get_paid_amount_for_client(request.user)

    # Per-project grouping
    projects_seen = {}
    for pr in payment_requests:
        pid = pr.project_id
        if pid not in projects_seen:
            # Per-project paid is transaction-based too
            proj_paid = service.get_paid_amount_for_project(pr.project)
            projects_seen[pid] = {
                "project":       pr.project,
                "requests":      [],
                "total_amount":  Decimal("0.00"),
                "total_paid":    proj_paid,
                "total_pending": Decimal("0.00"),
            }
        entry = projects_seen[pid]
        entry["requests"].append(pr)
        entry["total_amount"] += pr.amount
        if pr.status == PaymentRequest.Status.PENDING:
            entry["total_pending"] += pr.amount

    project_groups = list(projects_seen.values())

    # Grand totals
    agg = payment_requests.aggregate(total=Sum("amount"))
    grand_total     = agg["total"] or Decimal("0.00")
    grand_paid      = txn_paid_total                        # from transactions
    grand_pending   = payment_requests.filter(
        status=PaymentRequest.Status.PENDING
    ).aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
    grand_remaining = grand_total - grand_paid

    # Recent transactions for inline history (last 5)
    recent_transactions = (
        PaymentTransaction.objects
        .select_related("payment_request", "project")
        .filter(client=request.user)
        .order_by("-created_at")[:5]
    )

    return render(request, "payments/my_payments.html", {
        "project_groups":      project_groups,
        "grand_total":         grand_total,
        "grand_paid":          grand_paid,
        "grand_pending":       grand_pending,
        "grand_remaining":     grand_remaining,
        "recent_transactions": recent_transactions,
    })


# ─────────────────────────────────────────────────────────────────────────────
# MANAGER / STAFF OVERVIEW — /payments/   (Phase 2, unchanged)
# ─────────────────────────────────────────────────────────────────────────────

@staff_or_above
def payment_view(request):
    """Manager/Staff org-scoped overview of all PaymentRequests."""
    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(request, "You must complete organisation setup first.")
        return redirect("accounts:create_organization")

    payment_requests = (
        PaymentRequest.objects
        .select_related("project", "client", "created_by")
        .filter(project__organization=manager_org)
        .order_by("project__name", "created_at")
    )

    projects_seen = {}
    for pr in payment_requests:
        pid = pr.project_id
        if pid not in projects_seen:
            projects_seen[pid] = {
                "project":       pr.project,
                "requests":      [],
                "total_amount":  Decimal("0.00"),
                "total_paid":    Decimal("0.00"),
                "total_pending": Decimal("0.00"),
            }
        entry = projects_seen[pid]
        entry["requests"].append(pr)
        entry["total_amount"] += pr.amount
        if pr.status == PaymentRequest.Status.PAID:
            entry["total_paid"] += pr.amount
        elif pr.status == PaymentRequest.Status.PENDING:
            entry["total_pending"] += pr.amount

    project_groups = list(projects_seen.values())

    totals = payment_requests.aggregate(
        total_amount=Sum("amount"),
        total_paid=Sum("amount", filter=Q(status=PaymentRequest.Status.PAID)),
        total_pending=Sum("amount", filter=Q(status=PaymentRequest.Status.PENDING)),
    )
    grand_total   = totals["total_amount"]  or Decimal("0.00")
    grand_paid    = totals["total_paid"]    or Decimal("0.00")
    grand_pending = totals["total_pending"] or Decimal("0.00")

    status_counts = {
        "pending":   payment_requests.filter(status=PaymentRequest.Status.PENDING).count(),
        "paid":      payment_requests.filter(status=PaymentRequest.Status.PAID).count(),
        "overdue":   payment_requests.filter(status=PaymentRequest.Status.OVERDUE).count(),
        "cancelled": payment_requests.filter(status=PaymentRequest.Status.CANCELLED).count(),
    }

    return render(request, "payments/payment.html", {
        "project_groups":  project_groups,
        "grand_total":     grand_total,
        "grand_paid":      grand_paid,
        "grand_pending":   grand_pending,
        "status_counts":   status_counts,
        "organization":    manager_org,
    })


# ─────────────────────────────────────────────────────────────────────────────
# PROJECT-LEVEL PAYMENTS — /payments/project/<pk>/   (Phase 2, unchanged)
# ─────────────────────────────────────────────────────────────────────────────

@staff_or_above
def project_payments(request, project_pk):
    """Manager/Staff: all PaymentRequests for a single org-scoped project."""
    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(request, "You must complete organisation setup first.")
        return redirect("accounts:create_organization")

    project = get_object_or_404(
        Project.objects.select_related("client", "organization"),
        pk=project_pk,
        organization=manager_org,
    )

    payment_requests = (
        PaymentRequest.objects
        .select_related("client", "created_by")
        .filter(project=project)
        .order_by("created_at")
    )

    totals = payment_requests.aggregate(
        total_amount=Sum("amount"),
        total_paid=Sum("amount", filter=Q(status=PaymentRequest.Status.PAID)),
        total_pending=Sum("amount", filter=Q(status=PaymentRequest.Status.PENDING)),
    )
    total_amount  = totals["total_amount"]  or Decimal("0.00")
    total_paid    = totals["total_paid"]    or Decimal("0.00")
    total_pending = totals["total_pending"] or Decimal("0.00")
    remaining     = total_amount - total_paid

    # Phase 3: transaction history for this project (manager view)
    transactions = (
        PaymentTransaction.objects
        .select_related("payment_request", "client")
        .filter(project=project)
        .order_by("-created_at")[:20]
    )

    return render(request, "payments/project_payments.html", {
        "project":          project,
        "payment_requests": payment_requests,
        "total_amount":     total_amount,
        "total_paid":       total_paid,
        "total_pending":    total_pending,
        "remaining":        remaining,
        "create_form":      PaymentRequestForm(),
        "status_choices":   PaymentRequest.Status.choices,
        "transactions":     transactions,          # Phase 3 addition
    })


# ─────────────────────────────────────────────────────────────────────────────
# CREATE PAYMENT REQUEST — /payments/project/<pk>/create/   (Phase 2, unchanged)
# ─────────────────────────────────────────────────────────────────────────────

@manager_required
@require_http_methods(["POST"])
def create_payment_request(request, project_pk):
    """POST-only: Manager creates a new PaymentRequest for a project."""
    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(request, "Organisation setup required.")
        return redirect("accounts:create_organization")

    project = get_object_or_404(
        Project.objects.select_related("client"),
        pk=project_pk,
        organization=manager_org,
    )

    if not project.client:
        messages.error(
            request,
            f'Project "{project.name}" has no client assigned. '
            "Assign a client before creating payment requests.",
        )
        return redirect("payments:project_payments", project_pk=project_pk)

    form = PaymentRequestForm(request.POST)
    if form.is_valid():
        pr = form.save(commit=False)
        pr.project    = project
        pr.client     = project.client
        pr.created_by = request.user
        pr.status     = PaymentRequest.Status.PENDING
        pr.save()
        messages.success(
            request,
            f'Payment request "{pr.title}" (NPR {pr.amount:,.2f}) created successfully.',
        )
    else:
        error_text = " | ".join(
            f"{field}: {', '.join(errs)}"
            for field, errs in form.errors.items()
        )
        messages.error(request, f"Could not create payment request — {error_text}")

    return redirect("payments:project_payments", project_pk=project_pk)


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE PAYMENT STATUS — /payments/<pk>/status/   (Phase 2, unchanged)
# ─────────────────────────────────────────────────────────────────────────────

@manager_required
@require_http_methods(["POST"])
def update_payment_status(request, pk):
    """POST-only: Manager updates the status of a single PaymentRequest."""
    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(request, "Organisation setup required.")
        return redirect("accounts:create_organization")

    payment_request = get_object_or_404(
        PaymentRequest.objects.select_related("project"),
        pk=pk,
        project__organization=manager_org,
    )

    form = PaymentStatusForm(request.POST)
    if form.is_valid():
        new_status = form.cleaned_data["status"]
        old_status = payment_request.status
        payment_request.status = new_status
        payment_request.save(update_fields=["status", "updated_at"])

        status_label = dict(PaymentRequest.Status.choices).get(new_status, new_status)
        messages.success(
            request,
            f'"{payment_request.title}" status updated to {status_label}.',
        )
        logger.info(
            "PaymentRequest #%d status changed %s → %s by %s",
            pk, old_status, new_status, request.user.username,
        )
    else:
        messages.error(request, "Invalid status value.")

    return redirect("payments:project_payments", project_pk=payment_request.project_id)


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 3 VIEWS
# ═════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# INITIATE PAYMENT — /payments/initiate/<pr_pk>/
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def initiate_payment(request, pr_pk):
    """
    GET  — Show the payment confirmation page for a specific PaymentRequest.
    POST — Create a PaymentTransaction (INITIATED), then redirect to simulate.

    Security:
      • The PaymentRequest is fetched with client=request.user — a client
        cannot initiate a payment for another client's request.
      • Amount is NEVER read from POST — always from the DB record.
      • Only PENDING requests can be paid (PAID/CANCELLED are rejected).
    """
    payment_request = get_object_or_404(
        PaymentRequest.objects.select_related("project", "client"),
        pk=pr_pk,
        client=request.user,          # ownership enforced at DB level
    )

    if request.method == "GET":
        # Show confirmation page
        return render(request, "payments/payment_processing.html", {
            "payment_request": payment_request,
            "is_dev": settings.DEBUG,
        })

    # POST — initiate the transaction
    try:
        txn = service.initiate_payment(
            payment_request=payment_request,
            client=request.user,
            method=PaymentTransaction.PaymentMethod.SIMULATION,
        )
    except service.PaymentAlreadyPaidError:
        messages.info(request, "This payment request has already been paid.")
        return redirect("payments:client_payments")
    except service.PaymentCancelledError:
        messages.error(request, "This payment request has been cancelled by your project manager.")
        return redirect("payments:client_payments")
    except service.PaymentError as exc:
        logger.error("initiate_payment failed for PR #%d: %s", pr_pk, exc)
        messages.error(request, "Could not initiate payment. Please try again.")
        return redirect("payments:client_payments")

    # In Phase 3 always go to the simulation page
    return redirect("payments:simulate_payment_result", txn_pk=txn.pk)


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATE PAYMENT RESULT — /payments/simulate/<txn_pk>/
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def simulate_payment_result(request, txn_pk):
    """
    GET  — Show the simulation choice page (Success / Fail buttons).
    POST — Process the simulated outcome.

    PRODUCTION GUARD: returns Http404 when DEBUG=False.
    This view must never be reachable in a live deployment without DEBUG=True.

    Security:
      • The transaction is fetched with client=request.user — a client
        cannot simulate a result for another client's transaction.
      • Status can only be advanced by the service layer — POST data
        contains only the outcome choice, not the new status string.
      • 'outcome' must be exactly "success" or "failed" — any other value
        is silently treated as a failure.
    """
    if not settings.DEBUG:
        raise Http404("Simulation endpoint is disabled in production.")

    txn = get_object_or_404(
        PaymentTransaction.objects.select_related("payment_request", "project", "client"),
        pk=txn_pk,
        client=request.user,          # ownership enforced at DB level
    )

    # If the transaction has already been resolved (e.g. user hit back),
    # redirect straight to the result page.
    if txn.status != PaymentTransaction.Status.INITIATED:
        return redirect("payments:payment_result", txn_pk=txn.pk)

    if request.method == "GET":
        return render(request, "payments/simulate.html", {
            "txn":             txn,
            "payment_request": txn.payment_request,
        })

    # POST: process outcome
    outcome = request.POST.get("outcome", "failed").strip().lower()

    if outcome == "success":
        try:
            service.record_success(txn)
        except service.InvalidTransactionError as exc:
            logger.warning("simulate success rejected: %s", exc)
            messages.error(request, "This transaction has already been processed.")
    else:
        try:
            service.record_failure(txn, reason="Simulated failure by client in dev/test.")
        except service.InvalidTransactionError as exc:
            logger.warning("simulate failure rejected: %s", exc)
            messages.error(request, "This transaction has already been processed.")

    return redirect("payments:payment_result", txn_pk=txn.pk)


# ─────────────────────────────────────────────────────────────────────────────
# PAYMENT RESULT — /payments/result/<txn_pk>/
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def payment_result(request, txn_pk):
    """
    Read-only: show the outcome of a specific PaymentTransaction.

    Security:
      • Fetched with client=request.user — a client cannot view another
        client's transaction result.
    """
    txn = get_object_or_404(
        PaymentTransaction.objects.select_related(
            "payment_request", "project", "client"
        ),
        pk=txn_pk,
        client=request.user,
    )
    return render(request, "payments/payment_result.html", {
        "txn":             txn,
        "payment_request": txn.payment_request,
        "project":         txn.project,
    })


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTION HISTORY — /payments/history/
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def transaction_history(request):
    """
    Full transaction history for the logged-in user.

    CLIENT: sees only their own transactions.
    MANAGER/STAFF: sees all transactions for projects in their org.

    Security:
      • CLIENT queryset always filters client=request.user.
      • MANAGER/STAFF queryset filters project__organization=manager_org.
    """
    if request.user.is_client:
        transactions = (
            PaymentTransaction.objects
            .select_related("payment_request", "project", "project__organization")
            .filter(client=request.user)
            .order_by("-created_at")
        )
        context = {
            "transactions": transactions,
            "is_client_view": True,
        }
    else:
        manager_org = get_user_organization(request.user)
        if manager_org is None:
            messages.error(request, "Organisation setup required.")
            return redirect("accounts:create_organization")

        transactions = (
            PaymentTransaction.objects
            .select_related(
                "payment_request", "project", "client"
            )
            .filter(project__organization=manager_org)
            .order_by("-created_at")
        )
        context = {
            "transactions":   transactions,
            "is_client_view": False,
            "organization":   manager_org,
        }

    return render(request, "payments/transaction_history.html", context)

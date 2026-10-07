"""
payments/views.py
─────────────────
Phase 2 — PaymentRequest CRUD (manager) + client payment list
Phase 3 — PaymentTransaction lifecycle: initiate, simulate, result, history
Phase 4 — Balance enforcement, over-request guard, email, financial summary

Security model
──────────────
• All sensitive values (amount, project, client, balance) are always
  derived server-side from DB records — NEVER from POST data.
• simulate_payment_result returns 404 when DEBUG=False.
• All client views filter strictly by client=request.user.
• All manager views filter by project__organization=manager_org.
• The service layer is the ONLY code that writes PaymentTransaction rows
  or transitions PaymentRequest.status.
• create_payment_request uses select_for_update() + transaction.atomic()
  to prevent concurrent over-requests for the same project.

Phase 4 balance calculation
────────────────────────────
  paid      = SUM of PaymentTransaction.amount WHERE status=SUCCESS
  pending   = SUM of PaymentRequest.amount WHERE status IN (PENDING, OVERDUE)
  available = max(0, project.budget - paid - pending)

  A new PaymentRequest.amount must be > 0 and <= available.
  This is enforced in both:
    (a) PaymentRequestForm.clean_amount() — catches it before save
    (b) The view — recomputes available inside the lock to catch races
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Sum, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from accounts.decorators import manager_required, staff_or_above
from accounts.views import get_user_organization
from projects.models import Project

from .forms import PaymentRequestForm, PaymentStatusForm
from .models import PaymentRequest, PaymentTransaction
from . import service

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CLIENT VIEW — /payments/my/
# Phase 4: adds project budget + financial summary per-project group
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def client_payments(request):
    """
    Show all PaymentRequests for the logged-in CLIENT.

    Per-project groups now include full financial summary from the service
    layer (budget, paid, pending, available, is_fully_paid) so the client
    sees exactly what the project costs and where it stands.
    """
    payment_requests = (
        PaymentRequest.objects
        .select_related("project", "project__organization", "created_by")
        .filter(client=request.user)
        .order_by("project__name", "created_at")
    )

    # Transaction-based paid total — authoritative source
    txn_paid_total = service.get_paid_amount_for_client(request.user)

    # Per-project grouping with full financial summary
    projects_seen = {}
    for pr in payment_requests:
        pid = pr.project_id
        if pid not in projects_seen:
            summary = service.get_project_financial_summary(pr.project)
            projects_seen[pid] = {
                "project":        pr.project,
                "requests":       [],
                "total_amount":   Decimal("0.00"),   # sum of PR amounts billed
                "total_paid":     summary["paid"],
                "total_pending":  summary["pending"],
                "available":      summary["available"],
                "is_fully_paid":  summary["is_fully_paid"],
                "budget":         summary["budget"],
            }
        entry = projects_seen[pid]
        entry["requests"].append(pr)
        entry["total_amount"] += pr.amount

    project_groups = list(projects_seen.values())

    # Grand totals
    agg = payment_requests.aggregate(total=Sum("amount"))
    grand_total     = agg["total"] or Decimal("0.00")
    grand_paid      = txn_paid_total
    grand_pending   = (
        payment_requests
        .filter(status=PaymentRequest.Status.PENDING)
        .aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
    )
    grand_remaining = max(Decimal("0.00"), grand_total - grand_paid)

    # Recent transactions (last 5) for inline history strip
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
# MANAGER / STAFF OVERVIEW — /payments/
# Phase 4: consistent transaction-based paid totals
# ─────────────────────────────────────────────────────────────────────────────

@staff_or_above
def payment_view(request):
    """
    Org-scoped overview of all projects with payment activity.

    Phase 4: per-project paid totals now come from PaymentTransactions
    (status=SUCCESS), matching the source of truth used everywhere else.
    The overview also shows available remaining per project so managers
    can see at a glance which projects still have budget to request against.
    """
    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(request, "You must complete organisation setup first.")
        return redirect("accounts:create_organization")

    payment_requests = (
        PaymentRequest.objects
        .select_related("project", "project__organization", "client", "created_by")
        .filter(project__organization=manager_org)
        .order_by("project__name", "created_at")
    )

    # Group by project; compute per-project financials from transactions
    projects_seen = {}
    for pr in payment_requests:
        pid = pr.project_id
        if pid not in projects_seen:
            summary = service.get_project_financial_summary(pr.project)
            projects_seen[pid] = {
                "project":       pr.project,
                "requests":      [],
                "total_amount":  Decimal("0.00"),
                "total_paid":    summary["paid"],
                "total_pending": summary["pending"],
                "available":     summary["available"],
                "is_fully_paid": summary["is_fully_paid"],
                "budget":        summary["budget"],
            }
        entry = projects_seen[pid]
        entry["requests"].append(pr)
        entry["total_amount"] += pr.amount

    project_groups = list(projects_seen.values())

    # Grand totals — transaction-based paid
    all_projects_in_org = Project.objects.filter(organization=manager_org)
    grand_paid    = Decimal("0.00")
    grand_pending = Decimal("0.00")
    for group in project_groups:
        grand_paid    += group["total_paid"]
        grand_pending += group["total_pending"]

    grand_total = (
        payment_requests.aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
    )

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
# PROJECT-LEVEL PAYMENTS — /payments/project/<pk>/
# Phase 4: full financial summary + fully-paid state
# ─────────────────────────────────────────────────────────────────────────────

@staff_or_above
def project_payments(request, project_pk):
    """
    All PaymentRequests for a single project, with full Phase 4 financial
    context: budget, paid (txn-based), pending, available remaining.
    """
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

    # Full Phase 4 financial summary
    summary = service.get_project_financial_summary(project)

    # Build an initial form; amount pre-populated with available balance
    available = summary["available"]
    create_form = PaymentRequestForm(
        max_amount=available if available > Decimal("0.00") else None,
        initial_amount=available if available > Decimal("0.00") else None,
    )

    # Phase 3: recent transaction history for this project
    transactions = (
        PaymentTransaction.objects
        .select_related("payment_request", "client")
        .filter(project=project)
        .order_by("-created_at")[:20]
    )

    return render(request, "payments/project_payments.html", {
        "project":          project,
        "payment_requests": payment_requests,
        # Phase 4 financial summary (consistent names across templates)
        "budget":           summary["budget"],
        "total_paid":       summary["paid"],
        "total_pending":    summary["pending"],
        "available":        summary["available"],
        "is_fully_paid":    summary["is_fully_paid"],
        # Legacy aliases kept so existing template references still work
        "total_amount":     payment_requests.aggregate(
                                t=Sum("amount"))["t"] or Decimal("0.00"),
        "remaining":        summary["available"],
        # Form and status choices
        "create_form":      create_form,
        "status_choices":   PaymentRequest.Status.choices,
        # Transactions
        "transactions":     transactions,
    })


# ─────────────────────────────────────────────────────────────────────────────
# CREATE PAYMENT REQUEST — /payments/project/<pk>/create/
# Phase 4: select_for_update concurrency lock, available-amount guard,
#          transaction.on_commit email notification
# ─────────────────────────────────────────────────────────────────────────────

@manager_required
@require_http_methods(["POST"])
def create_payment_request(request, project_pk):
    """
    POST-only: Manager creates a new PaymentRequest for a project.

    Phase 4 changes
    ───────────────
    1. Concurrency: wraps the entire create in transaction.atomic() and
       calls select_for_update() on the Project row.  This serialises
       concurrent POST requests so two managers cannot both create
       requests that together exceed the available balance.

    2. Available-amount guard: recomputes available_amount inside the
       lock and passes it as max_amount to PaymentRequestForm, which then
       enforces it in clean_amount().  A direct POST with a manipulated
       amount larger than available is rejected here, not just in HTML.

    3. Fully-paid block: rejects the request immediately if the project
       is already fully paid (available == 0 and no balance to request).

    4. Email: on successful creation, schedules an email to the client
       via transaction.on_commit() so the email only fires after the DB
       row is committed.  Email errors are caught and logged; they never
       roll back the PaymentRequest.

    Security
    ────────
    • project.client is ALWAYS set server-side (never from POST).
    • amount is validated against the server-computed available balance.
    • The organisation is ALWAYS verified via `organization=manager_org`.
    """
    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(request, "Organisation setup required.")
        return redirect("accounts:create_organization")

    # ── Acquire row-level lock + validate inside a single atomic block ────────
    try:
        with db_transaction.atomic():
            # select_for_update locks the Project row for the duration of
            # this transaction so no concurrent request can read a stale
            # available_amount before we finish writing.
            project = get_object_or_404(
                Project.objects.select_related("client").select_for_update(),
                pk=project_pk,
                organization=manager_org,
            )

            if not project.client:
                # Cannot create a PR without a client — surface error outside
                # the atomic block to avoid suppressing the exception.
                raise ValueError("no_client")

            # Recompute available amount inside the lock so we see the latest
            # committed state even if another request just created a PR.
            available = service.get_available_amount_for_project(project)

            # Hard block: project budget fully committed, no more requests.
            if available <= Decimal("0.00"):
                raise ValueError("fully_paid")

            form = PaymentRequestForm(
                request.POST,
                max_amount=available,      # server-side ceiling
            )

            if not form.is_valid():
                # Re-raise as a sentinel so we can handle outside atomic
                raise ValueError("form_invalid")

            pr = form.save(commit=False)
            pr.project    = project           # server-side only
            pr.client     = project.client    # server-side only
            pr.created_by = request.user      # server-side only
            pr.status     = PaymentRequest.Status.PENDING
            pr.save()

            # Capture values for the on_commit closure BEFORE the request
            # object is potentially recycled.
            pr_pk      = pr.pk
            login_url  = request.build_absolute_uri(reverse("accounts:login"))
            pr_title   = pr.title
            pr_amount  = pr.amount

            # Email fires AFTER the atomic block commits successfully.
            # Capture `pr` in the closure now; it is safe because the row
            # exists in the DB at commit time.
            def _send_email(_pr=pr, _url=login_url):
                service.send_payment_request_email(_pr, _url)

            db_transaction.on_commit(_send_email)

    except ValueError as exc:
        sentinel = str(exc)

        if sentinel == "no_client":
            messages.error(
                request,
                f'Project "{project_pk}" has no client assigned. '
                "Assign a client before creating payment requests.",
            )
            return redirect("payments:project_payments", project_pk=project_pk)

        if sentinel == "fully_paid":
            messages.error(
                request,
                "This project has no remaining balance available. "
                "No further payment requests can be created.",
            )
            return redirect("payments:project_payments", project_pk=project_pk)

        if sentinel == "form_invalid":
            # Retrieve the project without a lock for the redirect (read-only)
            error_text = " | ".join(
                f"{field}: {', '.join(errs)}"
                for field, errs in form.errors.items()
            )
            messages.error(request, f"Could not create payment request — {error_text}")
            return redirect("payments:project_payments", project_pk=project_pk)

        # Any other unexpected ValueError — log and surface generic error
        logger.error("create_payment_request unexpected error: %s", exc)
        messages.error(request, "Something went wrong. Please try again.")
        return redirect("payments:project_payments", project_pk=project_pk)

    except Http404:
        # Project not found in this org — let Django render the standard 404.
        raise

    except Exception as exc:
        logger.error("create_payment_request failed for project #%d: %s", project_pk, exc)
        messages.error(request, "Something went wrong. Please try again.")
        return redirect("payments:project_payments", project_pk=project_pk)

    messages.success(
        request,
        f'Payment request "{pr_title}" (NPR {pr_amount:,.2f}) created successfully. '
        f"The client has been notified by email.",
    )
    return redirect("payments:project_payments", project_pk=project_pk)


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE PAYMENT STATUS — /payments/<pk>/status/   (unchanged)
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
# PHASE 3 VIEWS  (unchanged from Phase 3)
# ═════════════════════════════════════════════════════════════════════════════

@login_required
def initiate_payment(request, pr_pk):
    """GET: confirm page. POST: create INITIATED transaction → simulate."""
    payment_request = get_object_or_404(
        PaymentRequest.objects.select_related("project", "client"),
        pk=pr_pk,
        client=request.user,
    )

    if request.method == "GET":
        project_summary = service.get_project_financial_summary(payment_request.project)
        return render(request, "payments/payment_processing.html", {
            "payment_request": payment_request,
            "project_summary": project_summary,
            "is_dev":          settings.DEBUG,
        })

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
        messages.error(
            request,
            "This payment request has been cancelled by your project manager.",
        )
        return redirect("payments:client_payments")
    except service.PaymentError as exc:
        logger.error("initiate_payment failed for PR #%d: %s", pr_pk, exc)
        messages.error(request, "Could not initiate payment. Please try again.")
        return redirect("payments:client_payments")

    return redirect("payments:simulate_payment_result", txn_pk=txn.pk)


@login_required
@require_http_methods(["GET", "POST"])
def simulate_payment_result(request, txn_pk):
    """Dev/test simulation endpoint. Returns 404 when DEBUG=False."""
    if not settings.DEBUG:
        raise Http404("Simulation endpoint is disabled in production.")

    txn = get_object_or_404(
        PaymentTransaction.objects.select_related("payment_request", "project", "client"),
        pk=txn_pk,
        client=request.user,
    )

    if txn.status != PaymentTransaction.Status.INITIATED:
        return redirect("payments:payment_result", txn_pk=txn.pk)

    if request.method == "GET":
        return render(request, "payments/simulate.html", {
            "txn":             txn,
            "payment_request": txn.payment_request,
        })

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


@login_required
def payment_result(request, txn_pk):
    """Read-only transaction result page."""
    txn = get_object_or_404(
        PaymentTransaction.objects.select_related("payment_request", "project", "client"),
        pk=txn_pk,
        client=request.user,
    )
    return render(request, "payments/payment_result.html", {
        "txn":             txn,
        "payment_request": txn.payment_request,
        "project":         txn.project,
    })


@login_required
def transaction_history(request):
    """Full transaction history — CLIENT sees own; MANAGER sees org-scoped."""
    if request.user.is_client:
        transactions = (
            PaymentTransaction.objects
            .select_related("payment_request", "project", "project__organization")
            .filter(client=request.user)
            .order_by("-created_at")
        )
        context = {"transactions": transactions, "is_client_view": True}
    else:
        manager_org = get_user_organization(request.user)
        if manager_org is None:
            messages.error(request, "Organisation setup required.")
            return redirect("accounts:create_organization")

        transactions = (
            PaymentTransaction.objects
            .select_related("payment_request", "project", "client")
            .filter(project__organization=manager_org)
            .order_by("-created_at")
        )
        context = {
            "transactions":   transactions,
            "is_client_view": False,
            "organization":   manager_org,
        }

    return render(request, "payments/transaction_history.html", context)

"""
payments/views.py
─────────────────
All views for the Payment Request workflow (Phase 2).

Security overview
─────────────────
client_payments         — login_required; CLIENT only sees their own requests
payment_view            — staff_or_above; org-scoped manager overview
project_payments        — staff_or_above; single project, org-scoped
create_payment_request  — manager_required; org-scoped project
update_payment_status   — manager_required; org-scoped project

All permission checks are enforced server-side — template button
visibility is decorative only.
"""

import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.decorators import manager_required, staff_or_above
from accounts.models import OrganizationMembership
from accounts.views import get_user_organization
from projects.models import Project

from .forms import PaymentRequestForm, PaymentStatusForm
from .models import PaymentRequest

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CLIENT VIEW — /payments/my/
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def client_payments(request):
    """
    Show all PaymentRequests for the logged-in CLIENT across all their projects.

    Security:
      - @login_required ensures authentication.
      - The queryset is always filtered to client=request.user so a client
        can NEVER see another client's payment requests, even by URL tampering.
      - Non-CLIENT users who reach this URL (e.g. staff trying /payments/my/)
        get their own empty view (harmless — they have no payment_requests).
        Managers are blocked at the middleware level from /payments/my/ is
        intentionally not blocked — but they have no PaymentRequest rows
        as client so they'd see an empty page; in practice they use
        /payments/ instead.
    """
    # All payment requests for this user across all their projects,
    # ordered oldest-first (natural chronological reading).
    payment_requests = (
        PaymentRequest.objects
        .select_related("project", "project__organization", "created_by")
        .filter(client=request.user)
        .order_by("project__name", "created_at")
    )

    # ── Per-project grouping for the template ────────────────────────────────
    # Build a list of dicts: {project, requests, subtotals}
    # Using Python grouping so we avoid a custom template tag.
    projects_seen = {}
    for pr in payment_requests:
        pid = pr.project_id
        if pid not in projects_seen:
            projects_seen[pid] = {
                "project": pr.project,
                "requests": [],
                "total_amount": Decimal("0.00"),
                "total_paid": Decimal("0.00"),
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

    # ── Global summary across all projects ──────────────────────────────────
    totals = payment_requests.aggregate(
        total_amount=Sum("amount"),
        total_paid=Sum("amount", filter=Q(status=PaymentRequest.Status.PAID)),
        total_pending=Sum("amount", filter=Q(status=PaymentRequest.Status.PENDING)),
    )
    grand_total   = totals["total_amount"]  or Decimal("0.00")
    grand_paid    = totals["total_paid"]    or Decimal("0.00")
    grand_pending = totals["total_pending"] or Decimal("0.00")
    grand_remaining = grand_total - grand_paid

    context = {
        "project_groups": project_groups,
        "grand_total":     grand_total,
        "grand_paid":      grand_paid,
        "grand_pending":   grand_pending,
        "grand_remaining": grand_remaining,
    }
    return render(request, "payments/my_payments.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# MANAGER / STAFF OVERVIEW — /payments/
# ─────────────────────────────────────────────────────────────────────────────

@staff_or_above
def payment_view(request):
    """
    Manager/Staff overview: all PaymentRequests across the organisation,
    grouped by project, with financial summaries.

    Organisation isolation: only shows projects belonging to the user's org.
    """
    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(request, "You must complete organisation setup first.")
        return redirect("accounts:create_organization")

    # All payment requests for projects in this org.
    payment_requests = (
        PaymentRequest.objects
        .select_related("project", "client", "created_by")
        .filter(project__organization=manager_org)
        .order_by("project__name", "created_at")
    )

    # Group by project (same pattern as client_payments above).
    projects_seen = {}
    for pr in payment_requests:
        pid = pr.project_id
        if pid not in projects_seen:
            projects_seen[pid] = {
                "project": pr.project,
                "requests": [],
                "total_amount": Decimal("0.00"),
                "total_paid": Decimal("0.00"),
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

    # Global summary
    totals = payment_requests.aggregate(
        total_amount=Sum("amount"),
        total_paid=Sum("amount", filter=Q(status=PaymentRequest.Status.PAID)),
        total_pending=Sum("amount", filter=Q(status=PaymentRequest.Status.PENDING)),
    )
    grand_total   = totals["total_amount"]  or Decimal("0.00")
    grand_paid    = totals["total_paid"]    or Decimal("0.00")
    grand_pending = totals["total_pending"] or Decimal("0.00")

    # Status filter counts for the overview (useful for the UI summary)
    status_counts = {
        "pending":   payment_requests.filter(status=PaymentRequest.Status.PENDING).count(),
        "paid":      payment_requests.filter(status=PaymentRequest.Status.PAID).count(),
        "overdue":   payment_requests.filter(status=PaymentRequest.Status.OVERDUE).count(),
        "cancelled": payment_requests.filter(status=PaymentRequest.Status.CANCELLED).count(),
    }

    context = {
        "project_groups":  project_groups,
        "grand_total":     grand_total,
        "grand_paid":      grand_paid,
        "grand_pending":   grand_pending,
        "status_counts":   status_counts,
        "organization":    manager_org,
    }
    return render(request, "payments/payment.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# PROJECT-LEVEL PAYMENTS — /payments/project/<pk>/
# ─────────────────────────────────────────────────────────────────────────────

@staff_or_above
def project_payments(request, project_pk):
    """
    Show all PaymentRequests for a single project.

    Organisation isolation: the project must belong to the user's org.
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

    totals = payment_requests.aggregate(
        total_amount=Sum("amount"),
        total_paid=Sum("amount", filter=Q(status=PaymentRequest.Status.PAID)),
        total_pending=Sum("amount", filter=Q(status=PaymentRequest.Status.PENDING)),
    )
    total_amount  = totals["total_amount"]  or Decimal("0.00")
    total_paid    = totals["total_paid"]    or Decimal("0.00")
    total_pending = totals["total_pending"] or Decimal("0.00")
    remaining     = total_amount - total_paid

    context = {
        "project":          project,
        "payment_requests": payment_requests,
        "total_amount":     total_amount,
        "total_paid":       total_paid,
        "total_pending":    total_pending,
        "remaining":        remaining,
        "create_form":      PaymentRequestForm(),
        # Pass status choices so the template can render the status radio buttons.
        "status_choices":   PaymentRequest.Status.choices,
    }
    return render(request, "payments/project_payments.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# CREATE PAYMENT REQUEST — /payments/project/<pk>/create/
# ─────────────────────────────────────────────────────────────────────────────

@manager_required
@require_http_methods(["POST"])
def create_payment_request(request, project_pk):
    """
    POST-only: Manager creates a new PaymentRequest for a project.

    Security:
      - @manager_required — STAFF and CLIENT cannot create payment requests.
      - Organisation isolation via `organization=manager_org` filter on project.
      - `client` and `project` are NEVER read from POST — they are derived
        server-side from the project record and the project's client FK.
    """
    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(request, "Organisation setup required.")
        return redirect("accounts:create_organization")

    project = get_object_or_404(
        Project.objects.select_related("client"),
        pk=project_pk,
        organization=manager_org,
    )

    # A project must have a client before a payment request can be created.
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
        pr.client     = project.client   # always server-side
        pr.created_by = request.user     # always server-side
        pr.status     = PaymentRequest.Status.PENDING
        pr.save()
        messages.success(
            request,
            f'Payment request "{pr.title}" (NPR {pr.amount:,.2f}) created successfully.',
        )
    else:
        # Collect all form errors into one message for simplicity.
        error_text = " | ".join(
            f"{field}: {', '.join(errs)}"
            for field, errs in form.errors.items()
        )
        messages.error(request, f"Could not create payment request — {error_text}")

    return redirect("payments:project_payments", project_pk=project_pk)


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE PAYMENT STATUS — /payments/<pk>/status/
# ─────────────────────────────────────────────────────────────────────────────

@manager_required
@require_http_methods(["POST"])
def update_payment_status(request, pk):
    """
    POST-only: Manager updates the status of a single PaymentRequest.

    Security:
      - @manager_required — STAFF and CLIENT are blocked here.
      - Organisation isolation: the payment request's project must belong to
        the manager's org.
      - Only valid status values (from PaymentStatusForm) are accepted;
        any other value results in a 400-style error message.
    """
    manager_org = get_user_organization(request.user)
    if manager_org is None:
        messages.error(request, "Organisation setup required.")
        return redirect("accounts:create_organization")

    # Fetch the payment request; enforce org isolation via project__organization.
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

    return redirect(
        "payments:project_payments",
        project_pk=payment_request.project_id,
    )

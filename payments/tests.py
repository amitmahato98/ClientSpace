"""
payments/tests.py
─────────────────
Phase 3 test suite covering all 10 scenarios specified in the brief.

Scenarios tested
────────────────
 1. Successful simulated transaction
 2. Failed simulated transaction
 3. PaymentRequest status changes correctly on success / stays PENDING on failure
 4. Successful payments appear in history
 5. Failed payments remain PENDING on the PaymentRequest
 6. Remaining balance is calculated correctly from transactions
 7. Client isolation (client cannot access another client's transaction)
 8. Organisation isolation (manager cannot access another org's payments)
 9. Manager access to payment history for their org
10. Duplicate / invalid transaction handling (idempotency guards)

Additional security tests
──────────────────────────
 S1. simulate endpoint returns 404 when DEBUG=False
 S2. initiate_payment rejects wrong-client ownership
 S3. Client cannot access manager payment overview
 S4. Amount is always server-side (cannot be overridden by POST)
"""

from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.urls import reverse

from accounts.models import Organization, OrganizationMembership
from projects.models import Project

from .models import PaymentRequest, PaymentTransaction
from .forms import PaymentRequestForm
from . import service

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_org_with_manager(username="mgr_test", email="mgr@test.local"):
    manager = User.objects.create_user(
        username=username, email=email, password="Test@1234!", role="MANAGER"
    )
    org = Organization.objects.create(name=f"Org-{username}", created_by=manager)
    OrganizationMembership.objects.create(user=manager, organization=org, role="MANAGER")
    return manager, org


def _make_client(org, username="cli_test", email="cli@test.local"):
    client_user = User.objects.create_user(
        username=username, email=email, password="Test@1234!", role="CLIENT"
    )
    OrganizationMembership.objects.create(user=client_user, organization=org, role="CLIENT")
    return client_user


def _make_project(manager, org, client_user, budget=Decimal("100000.00"), name="Test Project"):
    return Project.objects.create(
        name=name,
        organization=org,
        client=client_user,
        created_by=manager,
        budget=budget,
    )


def _make_payment_request(project, client_user, manager, amount=Decimal("20000.00"), title="Initial Payment"):
    return PaymentRequest.objects.create(
        project=project,
        client=client_user,
        created_by=manager,
        title=title,
        amount=amount,
        status=PaymentRequest.Status.PENDING,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Service layer tests (no HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class ServiceLayerTests(TestCase):
    """Tests the service layer functions directly, independent of HTTP."""

    def setUp(self):
        self.manager, self.org = _make_org_with_manager()
        self.client_user = _make_client(self.org)
        self.project = _make_project(self.manager, self.org, self.client_user)
        self.pr = _make_payment_request(self.project, self.client_user, self.manager)

    # ── Scenario 1: Successful simulated transaction ──────────────────────────

    def test_initiate_creates_initiated_transaction(self):
        """initiate_payment creates a PaymentTransaction in INITIATED state."""
        txn = service.initiate_payment(self.pr, self.client_user)
        self.assertEqual(txn.status, PaymentTransaction.Status.INITIATED)
        self.assertEqual(txn.payment_request, self.pr)
        self.assertEqual(txn.client, self.client_user)
        self.assertEqual(txn.project, self.project)

    def test_amount_is_always_from_db_not_caller(self):
        """Amount on the transaction equals the PR amount regardless of caller input."""
        txn = service.initiate_payment(self.pr, self.client_user)
        # Amount must equal the PR amount — callers cannot influence it.
        self.assertEqual(txn.amount, self.pr.amount)
        self.assertEqual(txn.amount, Decimal("20000.00"))

    def test_record_success_marks_transaction_success(self):
        """record_success sets txn.status=SUCCESS and records paid_at."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        txn.refresh_from_db()
        self.assertEqual(txn.status, PaymentTransaction.Status.SUCCESS)
        self.assertIsNotNone(txn.paid_at)

    def test_record_success_generates_reference_id(self):
        """record_success populates gateway_transaction_id for simulation."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        txn.refresh_from_db()
        self.assertTrue(txn.gateway_transaction_id.startswith("SIM-"))

    # ── Scenario 2: Failed simulated transaction ──────────────────────────────

    def test_record_failure_marks_transaction_failed(self):
        """record_failure sets txn.status=FAILED and stores reason."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_failure(txn, reason="Card declined.")
        txn.refresh_from_db()
        self.assertEqual(txn.status, PaymentTransaction.Status.FAILED)
        self.assertEqual(txn.failure_reason, "Card declined.")

    # ── Scenario 3: PaymentRequest status transitions ─────────────────────────

    def test_pr_becomes_paid_on_success(self):
        """PaymentRequest.status is atomically set to PAID on record_success."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        self.pr.refresh_from_db()
        self.assertEqual(self.pr.status, PaymentRequest.Status.PAID)

    def test_pr_stays_pending_on_failure(self):
        """PaymentRequest.status remains PENDING when transaction fails."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_failure(txn, reason="Timeout.")
        self.pr.refresh_from_db()
        self.assertEqual(self.pr.status, PaymentRequest.Status.PENDING)

    # ── Scenario 5: Failed payments remain pending ────────────────────────────

    def test_failed_transaction_preserved_in_db(self):
        """Failed transactions are kept — not deleted — for audit purposes."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_failure(txn)
        self.assertTrue(PaymentTransaction.objects.filter(
            pk=txn.pk, status=PaymentTransaction.Status.FAILED
        ).exists())

    def test_client_can_retry_after_failure(self):
        """After a failure, a new INITIATED transaction can be created on the same PR."""
        txn1 = service.initiate_payment(self.pr, self.client_user)
        service.record_failure(txn1)
        # PR is still PENDING so a retry is allowed
        txn2 = service.initiate_payment(self.pr, self.client_user)
        self.assertEqual(txn2.status, PaymentTransaction.Status.INITIATED)
        self.assertEqual(PaymentTransaction.objects.filter(payment_request=self.pr).count(), 2)

    # ── Scenario 6: Remaining balance calculation ─────────────────────────────

    def test_paid_amount_is_zero_before_any_transactions(self):
        paid = service.get_paid_amount_for_project(self.project)
        self.assertEqual(paid, Decimal("0.00"))

    def test_paid_amount_updates_on_success(self):
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        paid = service.get_paid_amount_for_project(self.project)
        self.assertEqual(paid, Decimal("20000.00"))

    def test_failed_transactions_not_counted_in_paid_amount(self):
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_failure(txn)
        paid = service.get_paid_amount_for_project(self.project)
        self.assertEqual(paid, Decimal("0.00"))

    def test_remaining_balance_calculation(self):
        """Remaining = total_pr_amount - successfully paid transactions."""
        pr2 = _make_payment_request(
            self.project, self.client_user, self.manager,
            amount=Decimal("30000.00"), title="Milestone 1"
        )
        # Pay the first PR
        txn1 = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn1)
        # Total billed = 20000 + 30000 = 50000; paid = 20000; remaining = 30000
        total_billed = self.pr.amount + pr2.amount
        paid = service.get_paid_amount_for_project(self.project)
        remaining = total_billed - paid
        self.assertEqual(remaining, Decimal("30000.00"))

    def test_multiple_successful_transactions_sum_correctly(self):
        pr2 = _make_payment_request(
            self.project, self.client_user, self.manager,
            amount=Decimal("30000.00"), title="Milestone 1"
        )
        txn1 = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn1)
        txn2 = service.initiate_payment(pr2, self.client_user)
        service.record_success(txn2)
        paid = service.get_paid_amount_for_project(self.project)
        self.assertEqual(paid, Decimal("50000.00"))

    # ── Scenario 10: Duplicate / invalid transaction handling ─────────────────

    def test_cannot_double_process_success(self):
        """record_success on an already-SUCCESS txn raises InvalidTransactionError."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        txn.refresh_from_db()
        with self.assertRaises(service.InvalidTransactionError):
            service.record_success(txn)

    def test_cannot_fail_already_successful_transaction(self):
        """record_failure on a SUCCESS txn raises InvalidTransactionError."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        txn.refresh_from_db()
        with self.assertRaises(service.InvalidTransactionError):
            service.record_failure(txn)

    def test_cannot_initiate_already_paid_request(self):
        """initiate_payment on a PAID PR raises PaymentAlreadyPaidError."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        self.pr.refresh_from_db()
        with self.assertRaises(service.PaymentAlreadyPaidError):
            service.initiate_payment(self.pr, self.client_user)

    def test_cannot_initiate_cancelled_request(self):
        """initiate_payment on a CANCELLED PR raises PaymentCancelledError."""
        self.pr.status = PaymentRequest.Status.CANCELLED
        self.pr.save()
        with self.assertRaises(service.PaymentCancelledError):
            service.initiate_payment(self.pr, self.client_user)

    # ── Security S2: wrong-client ownership ───────────────────────────────────

    def test_wrong_client_cannot_initiate_payment(self):
        """initiate_payment raises InvalidTransactionError for wrong client."""
        other_client = _make_client(self.org, "other_cli", "other@test.local")
        with self.assertRaises(service.InvalidTransactionError):
            service.initiate_payment(self.pr, other_client)

    # ── Scenario 7: Client isolation (service layer) ──────────────────────────

    def test_client_isolation_in_service(self):
        """get_paid_amount_for_client returns 0 for a client with no transactions."""
        other_client = _make_client(self.org, "iso_cli", "iso@test.local")
        paid = service.get_paid_amount_for_client(other_client)
        self.assertEqual(paid, Decimal("0.00"))

    def test_client_isolation_paid_amount_is_per_client(self):
        """Two clients' paid amounts are independent of each other."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        other_client = _make_client(self.org, "iso_cli2", "iso2@test.local")
        self.assertEqual(service.get_paid_amount_for_client(other_client), Decimal("0.00"))
        self.assertEqual(service.get_paid_amount_for_client(self.client_user), Decimal("20000.00"))


# ─────────────────────────────────────────────────────────────────────────────
# HTTP view tests
# ─────────────────────────────────────────────────────────────────────────────

class PaymentViewTests(TestCase):
    """Tests the HTTP views for the Phase 3 payment flow."""

    def setUp(self):
        self.manager, self.org = _make_org_with_manager("vmgr", "vmgr@test.local")
        self.client_user = _make_client(self.org, "vcli", "vcli@test.local")
        self.project = _make_project(self.manager, self.org, self.client_user)
        self.pr = _make_payment_request(self.project, self.client_user, self.manager)
        self.http = Client()   # Django test client

    def _login_client(self):
        self.http.force_login(self.client_user)

    def _login_manager(self):
        self.http.force_login(self.manager)

    # ── initiate_payment GET ──────────────────────────────────────────────────

    def test_initiate_get_shows_confirmation_page(self):
        self._login_client()
        url = reverse("payments:initiate_payment", kwargs={"pr_pk": self.pr.pk})
        resp = self.http.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "payments/payment_processing.html")
        self.assertEqual(resp.context["payment_request"], self.pr)

    def test_initiate_get_requires_login(self):
        url = reverse("payments:initiate_payment", kwargs={"pr_pk": self.pr.pk})
        resp = self.http.get(url)
        self.assertRedirects(resp, f"/login/?next={url}", fetch_redirect_response=False)

    def test_initiate_get_rejects_wrong_client(self):
        """A different client cannot see another client's initiate page."""
        other_client = _make_client(self.org, "wrongcli", "wrong@test.local")
        self.http.force_login(other_client)
        url = reverse("payments:initiate_payment", kwargs={"pr_pk": self.pr.pk})
        resp = self.http.get(url)
        self.assertEqual(resp.status_code, 404)

    # ── initiate_payment POST ─────────────────────────────────────────────────

    @override_settings(DEBUG=True)
    def test_initiate_post_creates_transaction_and_redirects(self):
        self._login_client()
        url = reverse("payments:initiate_payment", kwargs={"pr_pk": self.pr.pk})
        resp = self.http.post(url)
        self.assertEqual(PaymentTransaction.objects.count(), 1)
        txn = PaymentTransaction.objects.first()
        self.assertEqual(txn.status, PaymentTransaction.Status.INITIATED)
        self.assertRedirects(
            resp,
            reverse("payments:simulate_payment_result", kwargs={"txn_pk": txn.pk}),
            fetch_redirect_response=False,
        )

    @override_settings(DEBUG=True)
    def test_initiate_post_amount_not_from_post_data(self):
        """Amount on the created transaction always equals the PR amount."""
        self._login_client()
        url = reverse("payments:initiate_payment", kwargs={"pr_pk": self.pr.pk})
        # Attempt to pass a different amount in POST — must be ignored.
        self.http.post(url, data={"amount": "1.00"})
        txn = PaymentTransaction.objects.first()
        self.assertEqual(txn.amount, self.pr.amount)

    @override_settings(DEBUG=True)
    def test_initiate_post_rejects_already_paid_pr(self):
        """POSTing on a PAID PR redirects with an info message, no new txn."""
        self.pr.status = PaymentRequest.Status.PAID
        self.pr.save()
        self._login_client()
        url = reverse("payments:initiate_payment", kwargs={"pr_pk": self.pr.pk})
        resp = self.http.post(url)
        self.assertEqual(PaymentTransaction.objects.count(), 0)
        self.assertRedirects(resp, reverse("payments:client_payments"), fetch_redirect_response=False)

    # ── simulate_payment_result ───────────────────────────────────────────────

    @override_settings(DEBUG=True)
    def test_simulate_success_updates_pr_and_txn(self):
        self._login_client()
        txn = service.initiate_payment(self.pr, self.client_user)
        url = reverse("payments:simulate_payment_result", kwargs={"txn_pk": txn.pk})
        resp = self.http.post(url, data={"outcome": "success"})
        txn.refresh_from_db()
        self.pr.refresh_from_db()
        self.assertEqual(txn.status, PaymentTransaction.Status.SUCCESS)
        self.assertEqual(self.pr.status, PaymentRequest.Status.PAID)
        self.assertRedirects(
            resp,
            reverse("payments:payment_result", kwargs={"txn_pk": txn.pk}),
            fetch_redirect_response=False,
        )

    @override_settings(DEBUG=True)
    def test_simulate_failure_keeps_pr_pending(self):
        self._login_client()
        txn = service.initiate_payment(self.pr, self.client_user)
        url = reverse("payments:simulate_payment_result", kwargs={"txn_pk": txn.pk})
        self.http.post(url, data={"outcome": "failed"})
        txn.refresh_from_db()
        self.pr.refresh_from_db()
        self.assertEqual(txn.status, PaymentTransaction.Status.FAILED)
        self.assertEqual(self.pr.status, PaymentRequest.Status.PENDING)

    @override_settings(DEBUG=False)
    def test_simulate_returns_404_in_production(self):
        """simulate endpoint is disabled when DEBUG=False."""
        self._login_client()
        txn = service.initiate_payment(self.pr, self.client_user)
        url = reverse("payments:simulate_payment_result", kwargs={"txn_pk": txn.pk})
        resp = self.http.get(url)
        self.assertEqual(resp.status_code, 404)

    @override_settings(DEBUG=True)
    def test_simulate_rejects_wrong_client(self):
        """Client cannot simulate another client's transaction."""
        txn = service.initiate_payment(self.pr, self.client_user)
        other_client = _make_client(self.org, "sim_wrong", "simwrong@test.local")
        self.http.force_login(other_client)
        url = reverse("payments:simulate_payment_result", kwargs={"txn_pk": txn.pk})
        resp = self.http.post(url, data={"outcome": "success"})
        self.assertEqual(resp.status_code, 404)
        # Original transaction should still be INITIATED
        txn.refresh_from_db()
        self.assertEqual(txn.status, PaymentTransaction.Status.INITIATED)

    # ── payment_result ────────────────────────────────────────────────────────

    @override_settings(DEBUG=True)
    def test_result_page_shows_success(self):
        self._login_client()
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        url = reverse("payments:payment_result", kwargs={"txn_pk": txn.pk})
        resp = self.http.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "payments/payment_result.html")
        self.assertTrue(resp.context["txn"].is_success)

    @override_settings(DEBUG=True)
    def test_result_page_wrong_client_returns_404(self):
        txn = service.initiate_payment(self.pr, self.client_user)
        other_client = _make_client(self.org, "res_wrong", "reswrong@test.local")
        self.http.force_login(other_client)
        url = reverse("payments:payment_result", kwargs={"txn_pk": txn.pk})
        resp = self.http.get(url)
        self.assertEqual(resp.status_code, 404)

    # ── Scenario 4 & 7: transaction_history client isolation ──────────────────

    @override_settings(DEBUG=True)
    def test_client_history_shows_only_own_transactions(self):
        """Scenario 4: successful payments appear in history; cross-client isolation."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        self._login_client()
        url = reverse("payments:transaction_history")
        resp = self.http.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(txn, resp.context["transactions"])

    @override_settings(DEBUG=True)
    def test_other_client_sees_empty_history(self):
        """Scenario 7: other client sees no transactions."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        other_client = _make_client(self.org, "hist_other", "hother@test.local")
        self.http.force_login(other_client)
        url = reverse("payments:transaction_history")
        resp = self.http.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(txn, list(resp.context["transactions"]))
        self.assertEqual(list(resp.context["transactions"]), [])

    # ── Scenario 8: Organisation isolation ───────────────────────────────────

    def test_manager_cannot_access_other_org_project_payments(self):
        """Scenario 8: manager from a different org gets 404 on project_payments."""
        other_manager, other_org = _make_org_with_manager("omgr", "omgr@test.local")
        self.http.force_login(other_manager)
        url = reverse("payments:project_payments", kwargs={"project_pk": self.project.pk})
        resp = self.http.get(url)
        self.assertEqual(resp.status_code, 404)

    # ── Scenario 9: Manager access ───────────────────────────────────────────

    @override_settings(DEBUG=True)
    def test_manager_sees_own_org_transactions_in_history(self):
        """Scenario 9: manager can see transactions for their org's projects."""
        txn = service.initiate_payment(self.pr, self.client_user)
        service.record_success(txn)
        self._login_manager()
        url = reverse("payments:transaction_history")
        resp = self.http.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(txn, list(resp.context["transactions"]))

    # ── Security S3: CLIENT blocked from manager pages ────────────────────────

    def test_client_cannot_access_payment_overview(self):
        """Security: CLIENT role blocked from /payments/ by middleware."""
        self._login_client()
        resp = self.http.get(reverse("payments:payment_view"))
        self.assertEqual(resp.status_code, 403)

    def test_client_cannot_access_project_payments(self):
        """Security: CLIENT role blocked from /payments/project/<pk>/."""
        self._login_client()
        url = reverse("payments:project_payments", kwargs={"project_pk": self.project.pk})
        resp = self.http.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_client_cannot_create_payment_request(self):
        """Security: CLIENT cannot POST to create_payment_request."""
        self._login_client()
        url = reverse("payments:create_payment_request", kwargs={"project_pk": self.project.pk})
        resp = self.http.post(url, data={"title": "Hack", "amount": "1000"})
        self.assertEqual(resp.status_code, 403)

    def test_client_cannot_update_payment_status(self):
        """Security: CLIENT cannot POST to update_payment_status."""
        self._login_client()
        url = reverse("payments:update_payment_status", kwargs={"pk": self.pr.pk})
        resp = self.http.post(url, data={"status": "PAID"})
        self.assertEqual(resp.status_code, 403)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 tests
# ─────────────────────────────────────────────────────────────────────────────

class Phase4ServiceTests(TestCase):
    """
    Service-layer tests for Phase 4 financial calculation helpers.

    Covers:
      P4-S1   get_pending_amount_for_project includes PENDING + OVERDUE
      P4-S2   get_pending_amount_for_project excludes PAID and CANCELLED
      P4-S3   get_available_amount_for_project = budget - paid - pending
      P4-S4   get_available_amount clamped to 0 (never negative)
      P4-S5   get_project_financial_summary keys and values
      P4-S6   is_fully_paid True only when paid >= budget and pending == 0
      P4-S7   is_fully_paid False when pending requests still outstanding
      P4-S8   multi-step partial payment workflow (spec Steps 1–7)
      P4-S9   available decreases correctly as PRs are created then paid
    """

    def setUp(self):
        self.manager, self.org = _make_org_with_manager("p4mgr", "p4mgr@test.local")
        self.client_user = _make_client(self.org, "p4cli", "p4cli@test.local")
        self.project = _make_project(
            self.manager, self.org, self.client_user,
            budget=Decimal("90000.00"),
            name="Phase4 Project",
        )

    def _make_pr(self, amount, title="PR", status=PaymentRequest.Status.PENDING):
        pr = _make_payment_request(
            self.project, self.client_user, self.manager,
            amount=Decimal(str(amount)), title=title,
        )
        if status != PaymentRequest.Status.PENDING:
            pr.status = status
            pr.save()
        return pr

    # ── P4-S1: pending amount includes PENDING and OVERDUE ────────────────────

    def test_pending_amount_includes_pending_and_overdue(self):
        pr_pending = self._make_pr("20000", "Pending PR")
        pr_overdue = self._make_pr("10000", "Overdue PR", PaymentRequest.Status.OVERDUE)
        pending = service.get_pending_amount_for_project(self.project)
        self.assertEqual(pending, Decimal("30000.00"))

    # ── P4-S2: pending amount excludes PAID and CANCELLED ─────────────────────

    def test_pending_amount_excludes_paid_and_cancelled(self):
        pr_paid      = self._make_pr("20000", "Paid PR",      PaymentRequest.Status.PAID)
        pr_cancelled = self._make_pr("15000", "Cancelled PR", PaymentRequest.Status.CANCELLED)
        pending = service.get_pending_amount_for_project(self.project)
        self.assertEqual(pending, Decimal("0.00"))

    # ── P4-S3: available = budget - paid - pending ────────────────────────────

    def test_available_amount_calculation(self):
        # Pay 20 000 via a transaction
        pr = self._make_pr("20000", "Initial 20%")
        txn = service.initiate_payment(pr, self.client_user)
        service.record_success(txn)
        # Add a pending request of 30 000
        self._make_pr("30000", "Milestone 1")
        available = service.get_available_amount_for_project(self.project)
        # 90 000 - 20 000 paid - 30 000 pending = 40 000
        self.assertEqual(available, Decimal("40000.00"))

    # ── P4-S4: available clamped to 0 ─────────────────────────────────────────

    def test_available_never_negative(self):
        # Create PRs summing to more than budget
        self._make_pr("50000", "A")
        self._make_pr("50000", "B")
        available = service.get_available_amount_for_project(self.project)
        self.assertEqual(available, Decimal("0.00"))

    # ── P4-S5: financial summary keys ─────────────────────────────────────────

    def test_get_project_financial_summary_keys(self):
        summary = service.get_project_financial_summary(self.project)
        for key in ("budget", "paid", "pending", "available", "is_fully_paid"):
            self.assertIn(key, summary)
        self.assertEqual(summary["budget"], Decimal("90000.00"))
        self.assertEqual(summary["paid"], Decimal("0.00"))
        self.assertEqual(summary["pending"], Decimal("0.00"))
        self.assertEqual(summary["available"], Decimal("90000.00"))
        self.assertFalse(summary["is_fully_paid"])

    # ── P4-S6: is_fully_paid True when all budget paid and no pending ──────────

    def test_is_fully_paid_true(self):
        pr = self._make_pr("90000", "Full payment")
        txn = service.initiate_payment(pr, self.client_user)
        service.record_success(txn)
        summary = service.get_project_financial_summary(self.project)
        self.assertTrue(summary["is_fully_paid"])
        self.assertEqual(summary["available"], Decimal("0.00"))

    # ── P4-S7: is_fully_paid False when pending requests exist ────────────────

    def test_is_fully_paid_false_with_pending(self):
        # Pay 60 000, but still have 30 000 pending
        pr_paid = self._make_pr("60000", "Paid part")
        txn = service.initiate_payment(pr_paid, self.client_user)
        service.record_success(txn)
        self._make_pr("30000", "Still pending")
        summary = service.get_project_financial_summary(self.project)
        self.assertFalse(summary["is_fully_paid"])

    # ── P4-S8: multi-step partial payment workflow (spec steps 1–7) ───────────

    def test_multi_step_partial_payment_workflow(self):
        """
        Budget: 90 000
        Step 1: initial PR 20 000 → paid → available = 70 000
        Step 2: PR 30 000 created → available = 40 000
        Step 3: PR 25 000 created → available = 15 000
        Step 4: PR 15 000 created → available = 0 → fully paid
        """
        # Step 1: initial PR paid
        pr1 = self._make_pr("20000", "Initial (20%)")
        txn1 = service.initiate_payment(pr1, self.client_user)
        service.record_success(txn1)

        available = service.get_available_amount_for_project(self.project)
        self.assertEqual(available, Decimal("70000.00"))

        # Step 2: create 30 000 request
        pr2 = self._make_pr("30000", "Milestone 1")
        available = service.get_available_amount_for_project(self.project)
        self.assertEqual(available, Decimal("40000.00"))

        # Step 3: create 25 000 request
        pr3 = self._make_pr("25000", "Milestone 2")
        available = service.get_available_amount_for_project(self.project)
        self.assertEqual(available, Decimal("15000.00"))

        # Step 4: create 15 000 request
        pr4 = self._make_pr("15000", "Final Payment")
        available = service.get_available_amount_for_project(self.project)
        self.assertEqual(available, Decimal("0.00"))

        # Not fully paid yet (pending requests still outstanding)
        self.assertFalse(service.get_project_financial_summary(self.project)["is_fully_paid"])

        # Pay the remaining three
        for pr in (pr2, pr3, pr4):
            txn = service.initiate_payment(pr, self.client_user)
            service.record_success(txn)

        summary = service.get_project_financial_summary(self.project)
        self.assertTrue(summary["is_fully_paid"])
        self.assertEqual(summary["paid"], Decimal("90000.00"))
        self.assertEqual(summary["available"], Decimal("0.00"))

    # ── P4-S9: available tracks correctly across create + pay cycle ───────────

    def test_available_tracks_create_and_pay_cycle(self):
        pr = self._make_pr("20000", "20%")
        self.assertEqual(
            service.get_available_amount_for_project(self.project),
            Decimal("70000.00"),   # 90k - 0 paid - 20k pending
        )
        txn = service.initiate_payment(pr, self.client_user)
        service.record_success(txn)
        self.assertEqual(
            service.get_available_amount_for_project(self.project),
            Decimal("70000.00"),   # 90k - 20k paid - 0 pending
        )


class Phase4FormTests(TestCase):
    """
    Tests for PaymentRequestForm Phase 4 validation.

    Covers:
      P4-F1   amount > 0 still required
      P4-F2   amount > max_amount rejected
      P4-F3   amount == max_amount accepted (exact boundary)
      P4-F4   amount < max_amount accepted
      P4-F5   form without max_amount only enforces > 0
      P4-F6   initial_amount pre-populates unbound form
    """

    def test_amount_zero_rejected(self):
        form = PaymentRequestForm(
            data={"title": "T", "amount": "0", "description": "", "due_date": ""},
            max_amount=Decimal("50000"),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_amount_exceeds_max_rejected(self):
        form = PaymentRequestForm(
            data={"title": "T", "amount": "50001", "description": "", "due_date": ""},
            max_amount=Decimal("50000"),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)
        self.assertIn("50,000.00", form.errors["amount"][0])

    def test_amount_equals_max_accepted(self):
        form = PaymentRequestForm(
            data={"title": "T", "amount": "50000", "description": "", "due_date": ""},
            max_amount=Decimal("50000"),
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_amount_less_than_max_accepted(self):
        form = PaymentRequestForm(
            data={"title": "T", "amount": "30000", "description": "", "due_date": ""},
            max_amount=Decimal("50000"),
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_without_max_only_enforces_positive(self):
        form = PaymentRequestForm(
            data={"title": "T", "amount": "999999", "description": "", "due_date": ""},
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_initial_amount_presets_unbound_form(self):
        form = PaymentRequestForm(initial_amount=Decimal("70000"))
        self.assertEqual(form.initial.get("amount"), Decimal("70000"))


class Phase4ViewTests(TestCase):
    """
    HTTP-level tests for Phase 4 payment request creation flow.

    Covers:
      P4-V1   create_payment_request: valid amount creates PR + redirects
      P4-V2   create_payment_request: amount > available rejected (server-side)
      P4-V3   create_payment_request: zero amount rejected
      P4-V4   create_payment_request: blocked when project fully paid
      P4-V5   create_payment_request: email sent via on_commit (mocked)
      P4-V6   create_payment_request: email NOT sent on validation failure
      P4-V7   project_payments view contains financial summary context
      P4-V8   project_payments: is_fully_paid=True when budget exhausted
      P4-V9   client_payments: project group contains budget/available/is_fully_paid
      P4-V10  organization isolation on create_payment_request POST
    """

    def setUp(self):
        self.manager, self.org = _make_org_with_manager("p4vmgr", "p4vmgr@test.local")
        self.client_user = _make_client(self.org, "p4vcli", "p4vcli@test.local")
        self.project = _make_project(
            self.manager, self.org, self.client_user,
            budget=Decimal("90000.00"),
            name="Phase4 View Project",
        )
        # Auto-create initial 20% PR to mirror the real project_create flow
        self.initial_pr = _make_payment_request(
            self.project, self.client_user, self.manager,
            amount=Decimal("18000.00"),
            title="Initial Payment (20%)",
        )
        self.http = Client()

    def _login_manager(self):
        self.http.force_login(self.manager)

    def _login_client(self):
        self.http.force_login(self.client_user)

    def _create_url(self):
        return reverse(
            "payments:create_payment_request",
            kwargs={"project_pk": self.project.pk},
        )

    def _project_payments_url(self):
        return reverse(
            "payments:project_payments",
            kwargs={"project_pk": self.project.pk},
        )

    # ── P4-V1: valid creation ─────────────────────────────────────────────────

    def test_valid_create_makes_pr_and_redirects(self):
        self._login_manager()
        resp = self.http.post(self._create_url(), data={
            "title": "Milestone 1",
            "amount": "30000",
            "description": "",
            "due_date": "",
        })
        self.assertRedirects(resp, self._project_payments_url(), fetch_redirect_response=False)
        self.assertEqual(PaymentRequest.objects.filter(project=self.project).count(), 2)
        new_pr = PaymentRequest.objects.get(title="Milestone 1")
        self.assertEqual(new_pr.amount, Decimal("30000.00"))
        self.assertEqual(new_pr.status, PaymentRequest.Status.PENDING)
        self.assertEqual(new_pr.client, self.client_user)   # server-side
        self.assertEqual(new_pr.project, self.project)      # server-side

    # ── P4-V2: amount > available rejected server-side ────────────────────────

    def test_amount_exceeds_available_rejected(self):
        """
        Budget=90k, initial PR=18k pending → available=72k.
        Posting 80k must be rejected with an error message, no PR created.
        """
        self._login_manager()
        initial_count = PaymentRequest.objects.filter(project=self.project).count()
        resp = self.http.post(self._create_url(), data={
            "title": "Too Large",
            "amount": "80000",   # available = 72 000
            "description": "",
            "due_date": "",
        })
        # Redirects back to project_payments with an error
        self.assertRedirects(resp, self._project_payments_url(), fetch_redirect_response=False)
        # No new PR created
        self.assertEqual(
            PaymentRequest.objects.filter(project=self.project).count(),
            initial_count,
        )

    # ── P4-V3: zero amount rejected ───────────────────────────────────────────

    def test_zero_amount_rejected(self):
        self._login_manager()
        initial_count = PaymentRequest.objects.filter(project=self.project).count()
        self.http.post(self._create_url(), data={
            "title": "Zero", "amount": "0", "description": "", "due_date": "",
        })
        self.assertEqual(
            PaymentRequest.objects.filter(project=self.project).count(),
            initial_count,
        )

    # ── P4-V4: blocked when fully paid ────────────────────────────────────────

    def test_create_blocked_when_project_fully_paid(self):
        # Pay the full budget
        full_pr = _make_payment_request(
            self.project, self.client_user, self.manager,
            amount=Decimal("72000.00"), title="Rest",
        )
        txn1 = service.initiate_payment(self.initial_pr, self.client_user)
        service.record_success(txn1)
        txn2 = service.initiate_payment(full_pr, self.client_user)
        service.record_success(txn2)

        # available == 0 now
        self.assertEqual(service.get_available_amount_for_project(self.project), Decimal("0.00"))

        self._login_manager()
        initial_count = PaymentRequest.objects.filter(project=self.project).count()
        self.http.post(self._create_url(), data={
            "title": "Extra", "amount": "1000", "description": "", "due_date": "",
        })
        # No new PR created
        self.assertEqual(
            PaymentRequest.objects.filter(project=self.project).count(),
            initial_count,
        )

    # ── P4-V5: email scheduled on success (service function called) ───────────

    def test_email_service_called_on_successful_creation(self):
        """
        service.send_payment_request_email is called inside on_commit.
        Because TestCase rolls back the transaction, on_commit never fires
        in the normal test runner.  We verify by patching the service
        function and confirming it was registered to fire.

        A separate TransactionTestCase (Phase4EmailTransactionTests) tests
        that it actually fires after a real commit.
        """
        from unittest.mock import patch

        self._login_manager()
        # Patch send_payment_request_email so on_commit can call it
        # even if the TestCase infrastructure prevents real commits.
        with patch("payments.service.send_payment_request_email") as mock_email:
            with patch("django.db.transaction.on_commit", side_effect=lambda fn: fn()):
                resp = self.http.post(self._create_url(), data={
                    "title": "Email Test",
                    "amount": "20000",
                    "description": "",
                    "due_date": "",
                })
            self.assertTrue(
                mock_email.called,
                "send_payment_request_email should have been called",
            )

    # ── P4-V6: email NOT sent on validation failure ───────────────────────────

    def test_email_not_sent_on_validation_failure(self):
        from unittest.mock import patch

        self._login_manager()
        with patch("payments.service.send_payment_request_email") as mock_email:
            with patch("django.db.transaction.on_commit", side_effect=lambda fn: fn()):
                # Submit an invalid amount (exceeds available)
                self.http.post(self._create_url(), data={
                    "title": "Bad Request",
                    "amount": "999999",   # way over budget
                    "description": "",
                    "due_date": "",
                })
            mock_email.assert_not_called()

    # ── P4-V7: project_payments view passes financial summary ─────────────────

    def test_project_payments_view_has_financial_context(self):
        self._login_manager()
        resp = self.http.get(self._project_payments_url())
        self.assertEqual(resp.status_code, 200)
        for key in ("budget", "total_paid", "total_pending", "available", "is_fully_paid"):
            self.assertIn(key, resp.context, f"Missing context key: {key}")
        self.assertEqual(resp.context["budget"], Decimal("90000.00"))
        self.assertFalse(resp.context["is_fully_paid"])

    # ── P4-V8: project_payments shows is_fully_paid when budget exhausted ─────

    def test_project_payments_is_fully_paid_flag(self):
        # Pay entire budget
        full_pr = _make_payment_request(
            self.project, self.client_user, self.manager,
            amount=Decimal("72000.00"), title="Rest",
        )
        txn1 = service.initiate_payment(self.initial_pr, self.client_user)
        service.record_success(txn1)
        txn2 = service.initiate_payment(full_pr, self.client_user)
        service.record_success(txn2)

        self._login_manager()
        resp = self.http.get(self._project_payments_url())
        self.assertTrue(resp.context["is_fully_paid"])
        self.assertEqual(resp.context["available"], Decimal("0.00"))

    # ── P4-V9: client_payments groups contain Phase 4 financial context ────────

    def test_client_payments_groups_contain_budget_and_available(self):
        self._login_client()
        resp = self.http.get(reverse("payments:client_payments"))
        self.assertEqual(resp.status_code, 200)
        groups = resp.context["project_groups"]
        self.assertTrue(len(groups) > 0, "Expected at least one project group")
        group = groups[0]
        for key in ("budget", "total_paid", "total_pending", "available", "is_fully_paid"):
            self.assertIn(key, group, f"Missing group key: {key}")
        self.assertEqual(group["budget"], Decimal("90000.00"))

    # ── P4-V10: org isolation on create ──────────────────────────────────────

    def test_other_org_manager_cannot_create_pr(self):
        other_manager, _ = _make_org_with_manager("otheromgr", "otheromgr@test.local")
        self.http.force_login(other_manager)
        initial_count = PaymentRequest.objects.filter(project=self.project).count()
        resp = self.http.post(self._create_url(), data={
            "title": "Hack", "amount": "5000", "description": "", "due_date": "",
        })
        # 404 because organization filter prevents the project from being found
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(
            PaymentRequest.objects.filter(project=self.project).count(),
            initial_count,
        )


class Phase4EmailTransactionTests(TransactionTestCase):
    """
    Uses TransactionTestCase (real commits) so on_commit callbacks fire.
    Verifies that send_payment_request_email is actually called after a
    successful create_payment_request POST.
    """

    def setUp(self):
        self.manager, self.org = _make_org_with_manager("etmgr", "etmgr@test.local")
        self.client_user = _make_client(self.org, "etcli", "etcli@test.local")
        self.project = _make_project(
            self.manager, self.org, self.client_user,
            budget=Decimal("90000.00"),
            name="Email Txn Project",
        )
        self.http = Client()

    def test_email_fires_after_commit(self):
        from unittest.mock import patch

        self.http.force_login(self.manager)
        url = reverse(
            "payments:create_payment_request",
            kwargs={"project_pk": self.project.pk},
        )

        with patch("payments.service.send_mail") as mock_mail:
            resp = self.http.post(url, data={
                "title": "Commit Email Test",
                "amount": "20000",
                "description": "",
                "due_date": "",
            })
            # TransactionTestCase commits for real so on_commit fires
            self.assertTrue(mock_mail.called, "send_mail should fire after commit")
            recipient_list = mock_mail.call_args[1].get(
                "recipient_list",
                mock_mail.call_args[0][3] if mock_mail.call_args[0] else [],
            )
            self.assertIn(self.client_user.email, recipient_list)

    def test_email_not_fired_when_amount_invalid(self):
        from unittest.mock import patch

        self.http.force_login(self.manager)
        url = reverse(
            "payments:create_payment_request",
            kwargs={"project_pk": self.project.pk},
        )

        with patch("payments.service.send_mail") as mock_mail:
            self.http.post(url, data={
                "title": "Bad",
                "amount": "999999",   # exceeds available
                "description": "",
                "due_date": "",
            })
            mock_mail.assert_not_called()

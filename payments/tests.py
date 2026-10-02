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
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from accounts.models import Organization, OrganizationMembership
from projects.models import Project

from .models import PaymentRequest, PaymentTransaction
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

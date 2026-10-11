import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.errors import IdempotencyInProgressError, PaymentInProgressError
from app.models import IdempotencyRecord, Payment, PaymentStatus
from app.services.gateway import SandboxGateway
from app.services.idempotency import Claimed
from tests.conftest import new_key, pay


def payment_count(database) -> int:
    with database.session() as session:
        return session.scalar(select(func.count()).select_from(Payment))


def test_paying_installment_reduces_remaining_balance(client, plan, gateway):
    response = pay(client, plan["id"], 1)
    assert response.status_code == 201
    payment = response.json()
    assert payment["status"] == "succeeded"
    assert payment["amount"] == "300.00"
    assert payment["gateway_reference"].startswith("ch_sandbox_")

    updated = client.get(f"/api/v1/plans/{plan['id']}").json()
    assert updated["amount_paid"] == "300.00"
    assert updated["remaining_balance"] == "900.00"
    assert updated["installments"][0]["status"] == "paid"
    assert gateway.charges_made == 1


def test_same_key_replays_without_charging_again(client, plan, gateway, database):
    key = new_key()
    first = pay(client, plan["id"], 1, key=key)
    second = pay(client, plan["id"], 1, key=key)
    assert second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert gateway.charges_made == 1
    assert payment_count(database) == 1


def test_paid_installment_cannot_be_paid_again_with_new_key(client, plan, gateway):
    assert pay(client, plan["id"], 1).status_code == 201
    response = pay(client, plan["id"], 1)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "installment_already_paid"
    assert gateway.charges_made == 1


def test_declined_payment_leaves_installment_pending(client, plan, gateway):
    response = pay(client, plan["id"], 1, method="pm_card_insufficient_funds")
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["failure_code"] == "insufficient_funds"

    updated = client.get(f"/api/v1/plans/{plan['id']}").json()
    assert updated["installments"][0]["status"] == "pending"
    assert updated["remaining_balance"] == "1200.00"
    assert gateway.charges_made == 0


def test_retry_after_decline_with_new_key_succeeds(client, plan, gateway):
    declined = pay(client, plan["id"], 1, method="pm_card_declined")
    assert declined.json()["status"] == "failed"

    retried = pay(client, plan["id"], 1, method="pm_card_visa")
    assert retried.json()["status"] == "succeeded"
    attempts = client.get(f"/api/v1/plans/{plan['id']}/payments").json()
    assert [p["status"] for p in attempts] == ["failed", "succeeded"]
    assert gateway.charges_made == 1


def test_same_key_after_decline_replays_the_failure(client, plan, gateway, database):
    key = new_key()
    first = pay(client, plan["id"], 1, method="pm_card_declined", key=key)
    again = pay(client, plan["id"], 1, method="pm_card_declined", key=key)
    assert again.json() == first.json()
    assert again.headers["Idempotent-Replayed"] == "true"
    assert payment_count(database) == 1


def test_transient_gateway_error_is_retried_transparently(client, plan, gateway):
    response = pay(client, plan["id"], 1, method="pm_card_flaky")
    assert response.json()["status"] == "succeeded"
    assert response.json()["gateway_attempts"] == 2
    assert gateway.charges_made == 1


def test_exhausted_retries_fail_then_new_key_succeeds(client, plan, gateway):
    failed = pay(client, plan["id"], 2, method="pm_card_processing_error")
    assert failed.json()["status"] == "failed"
    assert failed.json()["failure_code"] == "processing_error"
    assert failed.json()["gateway_attempts"] == 3

    recovered = pay(client, plan["id"], 2, method="pm_card_visa")
    assert recovered.json()["status"] == "succeeded"
    assert gateway.charges_made == 1


def test_paying_every_installment_completes_the_plan(client, plan):
    for number in range(1, 5):
        assert pay(client, plan["id"], number).json()["status"] == "succeeded"
    final = client.get(f"/api/v1/plans/{plan['id']}").json()
    assert final["status"] == "completed"
    assert final["amount_paid"] == final["total_cost"] == "1200.00"
    assert final["remaining_balance"] == "0.00"


def test_unknown_installment_returns_404_and_releases_key(client, plan):
    key = new_key()
    missing = pay(client, str(uuid.uuid4()), 1, key=key)
    assert missing.status_code == 404
    # Nothing happened under that key, so it is free to use for a fresh request.
    assert pay(client, str(uuid.uuid4()), 1, key=key).status_code == 404
    other_plan_missing = pay(client, plan["id"], 9)
    assert other_plan_missing.status_code == 404


class LostResponseGateway(SandboxGateway):
    """Charges the card, then loses the response once, like a connection reset."""

    def __init__(self) -> None:
        super().__init__()
        self.dropped = False

    def charge(self, amount, currency, payment_method, idempotency_key):
        result = super().charge(amount, currency, payment_method, idempotency_key)
        if not self.dropped:
            self.dropped = True
            raise ConnectionResetError("connection reset by peer")
        return result


def test_interrupted_payment_resumes_with_same_key(plan, payment_service, database):
    gateway = LostResponseGateway()
    payment_service.gateway = gateway
    plan_id = uuid.UUID(plan["id"])
    key = new_key()

    with pytest.raises(ConnectionResetError):
        payment_service.pay_installment(plan_id, 1, "pm_card_visa", key)

    # While the outcome is unknown, a different key cannot start a second charge.
    with pytest.raises(PaymentInProgressError):
        payment_service.pay_installment(plan_id, 1, "pm_card_visa", new_key())

    resumed = payment_service.pay_installment(plan_id, 1, "pm_card_visa", key)
    assert resumed.body["status"] == "succeeded"
    assert gateway.charges_made == 1
    assert payment_count(database) == 1


def test_stale_in_progress_key_is_taken_over(idempotency, database):
    first = idempotency.begin("payments.create", "stale-key-123", "hash")
    assert isinstance(first, Claimed)
    with pytest.raises(IdempotencyInProgressError):
        idempotency.begin("payments.create", "stale-key-123", "hash")

    with database.engine.begin() as conn:
        conn.execute(
            update(IdempotencyRecord).values(locked_at=datetime.now(UTC) - timedelta(minutes=5))
        )
    takeover = idempotency.begin("payments.create", "stale-key-123", "hash")
    assert takeover == Claimed(first.record_id)
    with database.session() as session:
        assert (
            session.scalar(select(Payment).where(Payment.status == PaymentStatus.PENDING)) is None
        )

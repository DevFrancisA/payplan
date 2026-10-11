"""Races that must never produce a duplicate charge or plan.

Each test releases N threads at once through a barrier against a real PostgreSQL database,
with gateway latency added so requests overlap while the first one is in flight.
"""

import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.errors import AppError
from app.models import Installment, Payment, PaymentStatus, Plan
from app.schemas import PlanRequest
from app.services.gateway import SandboxGateway
from tests.conftest import PLAN_BODY, new_key

THREADS = 12


def race(fn, n: int = THREADS) -> list:
    barrier = threading.Barrier(n)

    def run(i: int):
        barrier.wait()
        try:
            return fn(i)
        except AppError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(run, range(n)))


@pytest.fixture
def slow_gateway(payment_service) -> SandboxGateway:
    gateway = SandboxGateway(latency_s=0.05)
    payment_service.gateway = gateway
    return gateway


@pytest.fixture
def plan_id(plan_service) -> uuid.UUID:
    result = plan_service.create(PlanRequest(**PLAN_BODY), new_key())
    return uuid.UUID(result.body["id"])


def test_concurrent_requests_with_same_key_charge_once(
    plan_id, payment_service, slow_gateway, database
):
    key = new_key()
    results = race(lambda _: payment_service.pay_installment(plan_id, 1, "pm_card_visa", key))

    successes = [r for r in results if not isinstance(r, AppError)]
    conflicts = [r for r in results if isinstance(r, AppError)]
    assert successes, "at least the winning request must succeed"
    assert all(r.body == successes[0].body for r in successes)
    assert all(e.code == "idempotency_key_in_progress" for e in conflicts)
    assert slow_gateway.charges_made == 1
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1


def test_concurrent_requests_with_different_keys_pay_installment_once(
    plan_id, payment_service, slow_gateway, database
):
    results = race(lambda _: payment_service.pay_installment(plan_id, 1, "pm_card_visa", new_key()))

    outcomes = Counter(r.code if isinstance(r, AppError) else r.body["status"] for r in results)
    assert outcomes["succeeded"] == 1
    assert set(outcomes) <= {"succeeded", "payment_in_progress", "installment_already_paid"}
    assert slow_gateway.charges_made == 1
    with database.session() as session:
        succeeded = select(func.count()).where(Payment.status == PaymentStatus.SUCCEEDED)
        assert session.scalar(succeeded) == 1


def test_concurrent_checkout_with_same_key_creates_one_plan(plan_service, database):
    key = new_key()
    request = PlanRequest(**PLAN_BODY)
    results = race(lambda _: plan_service.create(request, key))

    plan_ids = {r.body["id"] for r in results if not isinstance(r, AppError)}
    assert len(plan_ids) == 1
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Plan)) == 1
        assert session.scalar(select(func.count()).select_from(Installment)) == 4


def test_database_rejects_second_active_payment_for_installment(plan_id, database):
    """The partial unique index is the last line of defence if application checks are bypassed."""
    with database.session() as session:
        installment = session.scalar(
            select(Installment).where(Installment.plan_id == plan_id, Installment.number == 1)
        )

        def payment(status: PaymentStatus) -> Payment:
            return Payment(
                installment_id=installment.id,
                idempotency_key=new_key(),
                amount=installment.amount,
                currency="USD",
                payment_method="pm_card_visa",
                status=status,
                gateway_attempts=0,
            )

        session.add_all([payment(PaymentStatus.FAILED), payment(PaymentStatus.FAILED)])
        session.add(payment(PaymentStatus.SUCCEEDED))
        session.commit()

        session.add(payment(PaymentStatus.PENDING))
        with pytest.raises(IntegrityError):
            session.commit()

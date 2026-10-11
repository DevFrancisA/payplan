"""Paying an installment, exactly once.

Three layers stop a customer from being charged twice:

1. The Idempotency-Key: retries of the same request replay the stored response.
2. A row lock on the installment plus a partial unique index allowing only one pending or
   succeeded payment per installment: two different keys racing on one installment
   cannot both reach the gateway.
3. The gateway charge is keyed by our payment id, so resuming an interrupted payment
   re-asks the processor for the same charge instead of creating a new one.

Work is split into two short transactions around the gateway call so no database locks
are held while waiting on the network.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.errors import InstallmentAlreadyPaidError, NotFoundError, PaymentInProgressError
from app.models import (
    Installment,
    InstallmentStatus,
    Payment,
    PaymentStatus,
    Plan,
    PlanStatus,
)
from app.observability import metrics
from app.schemas import PaymentOut
from app.services.gateway import (
    ChargeResult,
    PaymentGateway,
    RetryPolicy,
    TransientGatewayError,
)
from app.services.idempotency import (
    Claimed,
    IdempotencyService,
    IdempotentResult,
    fingerprint,
)

PAY_INSTALLMENT_SCOPE = "payments.create"


@dataclass(frozen=True, slots=True)
class _Reservation:
    payment_id: uuid.UUID
    amount: Decimal
    currency: str


class PaymentService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        gateway: PaymentGateway,
        retry_policy: RetryPolicy,
        idempotency: IdempotencyService,
    ) -> None:
        self.session_factory = session_factory
        self.gateway = gateway
        self.retry_policy = retry_policy
        self.idempotency = idempotency

    def pay_installment(
        self, plan_id: uuid.UUID, number: int, payment_method: str, idempotency_key: str
    ) -> IdempotentResult:
        request_hash = fingerprint(
            {"plan_id": str(plan_id), "number": number, "payment_method": payment_method}
        )
        outcome = self.idempotency.begin(PAY_INSTALLMENT_SCOPE, idempotency_key, request_hash)
        if not isinstance(outcome, Claimed):
            return IdempotentResult(outcome.status_code, outcome.body, replayed=True)

        try:
            reservation = self._reserve(plan_id, number, payment_method, idempotency_key)
        except Exception:
            # Nothing was charged or written, so the key can be used again.
            self.idempotency.release(outcome.record_id)
            raise

        try:
            result, attempts = self._charge(reservation, payment_method)
            body = self._finalize(reservation.payment_id, result, attempts, outcome.record_id)
        except Exception:
            # The charge may or may not have happened. Leave the payment pending and let the
            # client retry with the same key; the gateway's own idempotency resolves it.
            self.idempotency.unlock(outcome.record_id)
            raise

        metrics.count("PaymentSucceeded" if result.succeeded else "PaymentFailed")
        return IdempotentResult(201, body, replayed=False)

    def _reserve(
        self, plan_id: uuid.UUID, number: int, payment_method: str, idempotency_key: str
    ) -> _Reservation:
        with self.session_factory.begin() as session:
            installment = session.execute(
                select(Installment)
                .join(Plan)
                .where(Installment.plan_id == plan_id, Installment.number == number)
                .with_for_update(of=Installment)
            ).scalar_one_or_none()
            if installment is None:
                raise NotFoundError(f"Installment {number} of plan {plan_id} not found.")
            currency = session.get_one(Plan, plan_id).currency

            # Resume a payment this same key started before being interrupted.
            resumed = session.execute(
                select(Payment).where(
                    Payment.idempotency_key == idempotency_key,
                    Payment.status == PaymentStatus.PENDING,
                )
            ).scalar_one_or_none()
            if resumed is not None:
                return _Reservation(resumed.id, resumed.amount, resumed.currency)

            if installment.status == InstallmentStatus.PAID:
                raise InstallmentAlreadyPaidError(f"Installment {number} is already paid.")

            payment = Payment(
                id=uuid.uuid4(),
                installment_id=installment.id,
                idempotency_key=idempotency_key,
                amount=installment.amount,
                currency=currency,
                payment_method=payment_method,
                status=PaymentStatus.PENDING,
            )
            session.add(payment)
            try:
                session.flush()
            except IntegrityError as exc:
                raise PaymentInProgressError(
                    f"Another payment for installment {number} is already in progress."
                ) from exc
            return _Reservation(payment.id, payment.amount, currency)

    def _charge(self, reservation: _Reservation, payment_method: str) -> tuple[ChargeResult, int]:
        try:
            return self.retry_policy.run(
                lambda: self.gateway.charge(
                    reservation.amount,
                    reservation.currency,
                    payment_method,
                    idempotency_key=str(reservation.payment_id),
                )
            )
        except TransientGatewayError:
            return (
                ChargeResult(
                    False,
                    failure_code="processing_error",
                    failure_message="The payment processor is unavailable. Please try again.",
                ),
                self.retry_policy.max_attempts,
            )

    def _finalize(
        self,
        payment_id: uuid.UUID,
        result: ChargeResult,
        attempts: int,
        idempotency_record_id: uuid.UUID,
    ) -> dict:
        with self.session_factory.begin() as session:
            payment = session.get_one(Payment, payment_id, with_for_update=True)
            installment = session.get_one(Installment, payment.installment_id, with_for_update=True)
            payment.gateway_attempts += attempts

            if result.succeeded:
                payment.status = PaymentStatus.SUCCEEDED
                payment.gateway_reference = result.reference
                installment.status = InstallmentStatus.PAID
                installment.paid_at = datetime.now(UTC)
                session.flush()
                self._complete_plan_if_paid(session, installment.plan_id)
            else:
                payment.status = PaymentStatus.FAILED
                payment.failure_code = result.failure_code
                payment.failure_message = result.failure_message

            session.flush()
            body = self.to_out(payment, installment).model_dump(mode="json")
            # Payment state and the cached response commit together.
            self.idempotency.complete(session, idempotency_record_id, 201, body)
            return body

    @staticmethod
    def _complete_plan_if_paid(session: Session, plan_id: uuid.UUID) -> None:
        plan = session.get_one(Plan, plan_id, with_for_update=True)
        unpaid = session.execute(
            select(Installment.id).where(
                Installment.plan_id == plan_id, Installment.status != InstallmentStatus.PAID
            )
        ).first()
        if unpaid is None:
            plan.status = PlanStatus.COMPLETED

    def list_for_plan(self, plan_id: uuid.UUID) -> list[PaymentOut]:
        with self.session_factory() as session:
            if session.get(Plan, plan_id) is None:
                raise NotFoundError(f"Plan {plan_id} not found.")
            rows = session.execute(
                select(Payment, Installment)
                .join(Installment)
                .where(Installment.plan_id == plan_id)
                .order_by(Payment.created_at)
            ).all()
            return [self.to_out(payment, installment) for payment, installment in rows]

    @staticmethod
    def to_out(payment: Payment, installment: Installment) -> PaymentOut:
        return PaymentOut(
            id=payment.id,
            plan_id=installment.plan_id,
            installment_number=installment.number,
            amount=payment.amount,
            currency=payment.currency,
            payment_method=payment.payment_method,
            status=payment.status,
            gateway_attempts=payment.gateway_attempts,
            gateway_reference=payment.gateway_reference,
            failure_code=payment.failure_code,
            failure_message=payment.failure_message,
            created_at=payment.created_at,
        )

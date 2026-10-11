import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.errors import AppError, NotFoundError
from app.models import Installment, InstallmentStatus, Plan
from app.schemas import InstallmentOut, InstallmentQuote, PlanOut, PlanRequest, QuoteResponse
from app.services.idempotency import (
    Claimed,
    IdempotencyService,
    IdempotentResult,
    fingerprint,
)
from app.services.schedule import PaymentSchedule, ScheduleCalculator

CREATE_PLAN_SCOPE = "plans.create"


class InvalidPlanError(AppError):
    status_code = 422
    code = "invalid_plan"


class PlanService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        idempotency: IdempotencyService,
        calculator: ScheduleCalculator | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.idempotency = idempotency
        self.calculator = calculator or ScheduleCalculator()

    def quote(self, request: PlanRequest) -> QuoteResponse:
        schedule = self._schedule(request)
        return QuoteResponse(
            principal=schedule.principal,
            apr=schedule.apr,
            frequency=schedule.frequency,
            currency=request.currency,
            installment_count=len(schedule.installments),
            total_interest=schedule.total_interest,
            total_cost=schedule.total_cost,
            installments=[
                InstallmentQuote(
                    number=i.number,
                    due_date=i.due_date,
                    amount=i.amount,
                    principal=i.principal,
                    interest=i.interest,
                    remaining_balance=i.remaining_balance,
                )
                for i in schedule.installments
            ],
        )

    def create(self, request: PlanRequest, idempotency_key: str) -> IdempotentResult:
        outcome = self.idempotency.begin(
            CREATE_PLAN_SCOPE, idempotency_key, fingerprint(request.model_dump(mode="json"))
        )
        if not isinstance(outcome, Claimed):
            return IdempotentResult(outcome.status_code, outcome.body, replayed=True)

        try:
            schedule = self._schedule(request)
            with self.session_factory.begin() as session:
                plan = self._build_plan(request, schedule)
                session.add(plan)
                session.flush()
                body = self.to_out(plan).model_dump(mode="json")
                # Plan rows and the stored response commit atomically, or not at all.
                self.idempotency.complete(session, outcome.record_id, 201, body)
        except Exception:
            self.idempotency.release(outcome.record_id)
            raise
        return IdempotentResult(201, body, replayed=False)

    def get(self, plan_id: uuid.UUID) -> PlanOut:
        with self.session_factory() as session:
            plan = session.execute(
                select(Plan).where(Plan.id == plan_id).options(selectinload(Plan.installments))
            ).scalar_one_or_none()
            if plan is None:
                raise NotFoundError(f"Plan {plan_id} not found.")
            return self.to_out(plan)

    def _schedule(self, request: PlanRequest) -> PaymentSchedule:
        try:
            return self.calculator.calculate(
                principal=request.principal,
                installment_count=request.installment_count,
                apr=request.apr,
                frequency=request.frequency,
                first_due=request.first_due_date or date.today(),
            )
        except ValueError as exc:
            raise InvalidPlanError(str(exc)) from exc

    @staticmethod
    def _build_plan(request: PlanRequest, schedule: PaymentSchedule) -> Plan:
        return Plan(
            id=uuid.uuid4(),
            principal=schedule.principal,
            apr=schedule.apr,
            frequency=schedule.frequency.value,
            installment_count=len(schedule.installments),
            currency=request.currency,
            total_interest=schedule.total_interest,
            total_cost=schedule.total_cost,
            installments=[
                Installment(
                    id=uuid.uuid4(),
                    number=i.number,
                    due_date=i.due_date,
                    amount=i.amount,
                    principal=i.principal,
                    interest=i.interest,
                    status=InstallmentStatus.PENDING,
                )
                for i in schedule.installments
            ],
        )

    @staticmethod
    def to_out(plan: Plan) -> PlanOut:
        paid = sum(
            (i.amount for i in plan.installments if i.status == InstallmentStatus.PAID),
            Decimal("0.00"),
        )
        return PlanOut(
            id=plan.id,
            status=plan.status,
            principal=plan.principal,
            apr=plan.apr,
            frequency=plan.frequency,
            currency=plan.currency,
            installment_count=plan.installment_count,
            total_interest=plan.total_interest,
            total_cost=plan.total_cost,
            amount_paid=paid,
            remaining_balance=plan.total_cost - paid,
            created_at=plan.created_at,
            installments=[InstallmentOut.model_validate(i) for i in plan.installments],
        )

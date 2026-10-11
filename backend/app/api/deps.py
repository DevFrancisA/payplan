from typing import Annotated

from fastapi import Depends, Header, Request

from app.services.gateway import RetryPolicy
from app.services.idempotency import IdempotencyService
from app.services.payments import PaymentService
from app.services.plans import PlanService

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=255,
        description=(
            "Client-generated unique key (a UUID v4 is recommended). Retrying with the same "
            "key and body returns the original response instead of repeating the operation."
        ),
    ),
]


def _idempotency(request: Request) -> IdempotencyService:
    state = request.app.state
    return IdempotencyService(state.db.session_factory, state.settings.idempotency_lock_timeout_s)


def get_plan_service(request: Request) -> PlanService:
    return PlanService(request.app.state.db.session_factory, _idempotency(request))


def get_payment_service(request: Request) -> PaymentService:
    state = request.app.state
    return PaymentService(
        state.db.session_factory,
        state.gateway,
        RetryPolicy(state.settings.gateway_max_attempts, state.settings.gateway_retry_base_delay_s),
        _idempotency(request),
    )


PlanServiceDep = Annotated[PlanService, Depends(get_plan_service)]
PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]

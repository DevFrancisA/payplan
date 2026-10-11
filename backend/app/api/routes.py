import uuid

from fastapi import APIRouter, Path, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import IdempotencyKey, PaymentServiceDep, PlanServiceDep
from app.schemas import (
    ErrorResponse,
    PaymentOut,
    PaymentRequest,
    PlanOut,
    PlanRequest,
    QuoteResponse,
    SandboxMethod,
)
from app.services.gateway import SANDBOX_PAYMENT_METHODS
from app.services.idempotency import IdempotentResult

router = APIRouter(prefix="/api/v1")
health_router = APIRouter(tags=["health"])

IDEMPOTENT_RESPONSES = {
    409: {"model": ErrorResponse, "description": "A request with this key is still running"},
    422: {"model": ErrorResponse, "description": "Validation error or key reused with a new body"},
}


def _idempotent_response(result: IdempotentResult) -> JSONResponse:
    headers = {"Idempotent-Replayed": "true"} if result.replayed else {}
    return JSONResponse(status_code=result.status_code, content=result.body, headers=headers)


@router.post(
    "/quotes",
    response_model=QuoteResponse,
    tags=["quotes"],
    summary="Simulate a payment plan",
    description=(
        "Calculates installment dates, amounts, interest, total cost and the remaining balance "
        "after each installment. Nothing is stored; call this as the shopper adjusts terms."
    ),
)
def create_quote(body: PlanRequest, plans: PlanServiceDep) -> QuoteResponse:
    return plans.quote(body)


@router.post(
    "/plans",
    status_code=status.HTTP_201_CREATED,
    response_model=PlanOut,
    tags=["plans"],
    summary="Check out with a payment plan",
    description="Creates a plan and its installment schedule. Requires an Idempotency-Key.",
    responses=IDEMPOTENT_RESPONSES,
)
def create_plan(
    body: PlanRequest, idempotency_key: IdempotencyKey, plans: PlanServiceDep
) -> JSONResponse:
    return _idempotent_response(plans.create(body, idempotency_key))


@router.get(
    "/plans/{plan_id}",
    response_model=PlanOut,
    tags=["plans"],
    summary="Get a plan with its installments and remaining balance",
    responses={404: {"model": ErrorResponse}},
)
def get_plan(plan_id: uuid.UUID, plans: PlanServiceDep) -> PlanOut:
    return plans.get(plan_id)


@router.post(
    "/plans/{plan_id}/installments/{number}/payments",
    status_code=status.HTTP_201_CREATED,
    response_model=PaymentOut,
    tags=["payments"],
    summary="Pay an installment",
    description=(
        "Charges the sandbox gateway for one installment. Declines are returned as a payment "
        "with `status: failed`; retry with a **new** Idempotency-Key to try again. Reusing the "
        "same key replays the original result without charging again."
    ),
    responses={
        **IDEMPOTENT_RESPONSES,
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "Already paid, or a payment is in flight"},
    },
)
def pay_installment(
    plan_id: uuid.UUID,
    body: PaymentRequest,
    idempotency_key: IdempotencyKey,
    payments: PaymentServiceDep,
    number: int = Path(ge=1, le=60),
) -> JSONResponse:
    return _idempotent_response(
        payments.pay_installment(plan_id, number, body.payment_method, idempotency_key)
    )


@router.get(
    "/plans/{plan_id}/payments",
    response_model=list[PaymentOut],
    tags=["payments"],
    summary="List payment attempts for a plan",
    responses={404: {"model": ErrorResponse}},
)
def list_payments(plan_id: uuid.UUID, payments: PaymentServiceDep) -> list[PaymentOut]:
    return payments.list_for_plan(plan_id)


@router.get(
    "/sandbox/payment-methods",
    response_model=list[SandboxMethod],
    tags=["payments"],
    summary="List sandbox test payment methods",
)
def sandbox_methods() -> list[SandboxMethod]:
    return [SandboxMethod(token=t, behavior=b) for t, b in SANDBOX_PAYMENT_METHODS.items()]


@health_router.get("/healthz", summary="Liveness probe")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/readyz", summary="Readiness probe (checks the database)")
def readyz(request: Request) -> dict[str, str]:
    with request.app.state.db.session() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ready"}

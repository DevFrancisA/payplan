import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import health_router, router
from app.config import Settings, get_settings
from app.db import Database
from app.errors import AppError, app_error_handler, error_body
from app.observability import RequestContextMiddleware, configure_logging, metrics
from app.services.gateway import PaymentGateway, SandboxGateway

logger = logging.getLogger("payplan")

DESCRIPTION = """
PayPlan shows shoppers exactly what a payment plan costs before checkout: every installment
date, the total cost including interest, and the remaining balance after each payment.

**Idempotency.** `POST /plans` and installment payments require an `Idempotency-Key` header.
Retrying a request with the same key returns the original response (marked with
`Idempotent-Replayed: true`) and never creates a second plan or charge.

**Sandbox.** Payments go to a simulated processor. Use the tokens from
`GET /api/v1/sandbox/payment-methods` to trigger successes, declines and timeouts.
"""


def create_app(settings: Settings | None = None, gateway: PaymentGateway | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    metrics.configure(settings.emf_enabled, settings.metrics_namespace, settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.db.dispose()

    app = FastAPI(
        title="PayPlan API",
        version="1.0.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "quotes", "description": "Simulate plans without saving anything"},
            {"name": "plans", "description": "Create and inspect payment plans"},
            {"name": "payments", "description": "Pay installments through the sandbox gateway"},
            {"name": "health", "description": "Load balancer probes"},
        ],
    )
    app.state.settings = settings
    app.state.db = Database(settings)
    app.state.gateway = gateway or SandboxGateway(latency_s=settings.gateway_latency_ms / 1000)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["Idempotent-Replayed", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(AppError, app_error_handler)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500, content=error_body("internal_error", "Something went wrong.")
        )

    app.include_router(router)
    app.include_router(health_router)
    return app

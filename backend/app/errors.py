from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class InstallmentAlreadyPaidError(ConflictError):
    code = "installment_already_paid"


class PaymentInProgressError(ConflictError):
    code = "payment_in_progress"


class IdempotencyInProgressError(ConflictError):
    code = "idempotency_key_in_progress"


class IdempotencyKeyReuseError(AppError):
    status_code = 422
    code = "idempotency_key_reused"


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))

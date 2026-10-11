import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models import InstallmentStatus, PaymentStatus, PlanStatus
from app.services.schedule import MAX_APR, MAX_INSTALLMENTS, MAX_PRINCIPAL, MIN_PRINCIPAL, Frequency

# Money goes over the wire as a string ("19.99") so clients never round-trip through floats.
MoneyStr = Annotated[
    Decimal,
    PlainSerializer(lambda v: f"{v:.2f}", return_type=str, when_used="json"),
]
# Rates are serialized without trailing zeros: "19.99", "0".
RateStr = Annotated[
    Decimal,
    PlainSerializer(lambda v: format(v.normalize(), "f"), return_type=str, when_used="json"),
]


class PlanRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "principal": "1200.00",
                    "installment_count": 4,
                    "frequency": "biweekly",
                    "apr": "0",
                    "first_due_date": "2026-10-01",
                }
            ]
        }
    )

    principal: Decimal = Field(
        ge=MIN_PRINCIPAL,
        le=MAX_PRINCIPAL,
        decimal_places=2,
        description="Purchase amount to finance",
    )
    installment_count: int = Field(ge=1, le=MAX_INSTALLMENTS)
    frequency: Frequency = Frequency.BIWEEKLY
    apr: Decimal = Field(default=Decimal("0"), ge=0, le=MAX_APR, decimal_places=3)
    first_due_date: date | None = Field(
        default=None, description="Due date of the first installment. Defaults to today."
    )
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class InstallmentQuote(BaseModel):
    number: int
    due_date: date
    amount: MoneyStr
    principal: MoneyStr
    interest: MoneyStr
    remaining_balance: MoneyStr = Field(description="Amount still owed after this installment")


class QuoteResponse(BaseModel):
    principal: MoneyStr
    apr: RateStr
    frequency: Frequency
    currency: str
    installment_count: int
    total_interest: MoneyStr
    total_cost: MoneyStr
    installments: list[InstallmentQuote]


class InstallmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: int
    due_date: date
    amount: MoneyStr
    principal: MoneyStr
    interest: MoneyStr
    status: InstallmentStatus
    paid_at: datetime | None


class PlanOut(BaseModel):
    id: uuid.UUID
    status: PlanStatus
    principal: MoneyStr
    apr: RateStr
    frequency: Frequency
    currency: str
    installment_count: int
    total_interest: MoneyStr
    total_cost: MoneyStr
    amount_paid: MoneyStr
    remaining_balance: MoneyStr
    created_at: datetime
    installments: list[InstallmentOut]


class PaymentRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"payment_method": "pm_card_visa"}]})

    payment_method: str = Field(
        pattern=r"^pm_[a-z0-9_]+$",
        max_length=64,
        description="Sandbox payment method token, e.g. pm_card_visa or pm_card_declined",
    )


class PaymentOut(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    installment_number: int
    amount: MoneyStr
    currency: str
    payment_method: str
    status: PaymentStatus
    gateway_attempts: int
    gateway_reference: str | None
    failure_code: str | None
    failure_message: str | None
    created_at: datetime


class SandboxMethod(BaseModel):
    token: str
    behavior: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail

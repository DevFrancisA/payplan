import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def _str_enum(enum_cls: type[enum.Enum]) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        length=16,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


Money = Numeric(12, 2)


class PlanStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"


class InstallmentStatus(enum.StrEnum):
    PENDING = "pending"
    PAID = "paid"


class PaymentStatus(enum.StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class IdempotencyStatus(enum.StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("principal > 0", name="ck_plans_principal_positive"),
        CheckConstraint("installment_count BETWEEN 1 AND 60", name="ck_plans_installment_count"),
        CheckConstraint("apr >= 0", name="ck_plans_apr_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    principal: Mapped[Decimal] = mapped_column(Money)
    apr: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    frequency: Mapped[str] = mapped_column(String(16))
    installment_count: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    total_interest: Mapped[Decimal] = mapped_column(Money)
    total_cost: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[PlanStatus] = mapped_column(_str_enum(PlanStatus), default=PlanStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    installments: Mapped[list["Installment"]] = relationship(
        back_populates="plan", order_by="Installment.number", cascade="all, delete-orphan"
    )


class Installment(Base):
    __tablename__ = "installments"
    __table_args__ = (
        UniqueConstraint("plan_id", "number", name="uq_installments_plan_number"),
        CheckConstraint("amount > 0", name="ck_installments_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    principal: Mapped[Decimal] = mapped_column(Money)
    interest: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[InstallmentStatus] = mapped_column(
        _str_enum(InstallmentStatus), default=InstallmentStatus.PENDING
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped[Plan] = relationship(back_populates="installments")
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="installment", order_by="Payment.created_at"
    )


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        # At most one in-flight or successful payment per installment. Failed payments are
        # excluded so the customer can retry after a decline.
        Index(
            "uq_payments_one_active_per_installment",
            "installment_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'succeeded')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    installment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("installments.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    payment_method: Mapped[str] = mapped_column(String(64))
    status: Mapped[PaymentStatus] = mapped_column(
        _str_enum(PaymentStatus), default=PaymentStatus.PENDING
    )
    gateway_attempts: Mapped[int] = mapped_column(Integer, default=0)
    gateway_reference: Mapped[str | None] = mapped_column(String(64), unique=True)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    installment: Mapped[Installment] = relationship(back_populates="payments")


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[IdempotencyStatus] = mapped_column(
        _str_enum(IdempotencyStatus), default=IdempotencyStatus.IN_PROGRESS
    )
    # NULL means the record is unlocked and the next request with this key may resume it.
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

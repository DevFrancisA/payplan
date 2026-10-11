"""Installment schedule calculation.

Every amount is a ``Decimal`` rounded to cents, and the schedule always reconciles exactly:
the installment principals sum to the financed amount, and the installment amounts sum to
``total_cost``. Rounding drift is absorbed by a single installment instead of being lost.
"""

import calendar
import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext

from app.services.money import CENT, to_money

MIN_PRINCIPAL = Decimal("1.00")
MAX_PRINCIPAL = Decimal("100000.00")
MAX_INSTALLMENTS = 60
MAX_APR = Decimal("36")


class Frequency(enum.StrEnum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class DueDateStrategy(ABC):
    periods_per_year: int

    @abstractmethod
    def due_date(self, first_due: date, index: int) -> date:
        """Due date of the installment at zero-based ``index``."""


class FixedIntervalStrategy(DueDateStrategy):
    def __init__(self, days: int, periods_per_year: int) -> None:
        self.days = days
        self.periods_per_year = periods_per_year

    def due_date(self, first_due: date, index: int) -> date:
        return first_due + timedelta(days=self.days * index)


class MonthlyStrategy(DueDateStrategy):
    """Same day each month, clamped to month end (Jan 31 -> Feb 28 -> Mar 31)."""

    periods_per_year = 12

    def due_date(self, first_due: date, index: int) -> date:
        month_index = first_due.month - 1 + index
        year = first_due.year + month_index // 12
        month = month_index % 12 + 1
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(first_due.day, last_day))


STRATEGIES: dict[Frequency, DueDateStrategy] = {
    Frequency.WEEKLY: FixedIntervalStrategy(days=7, periods_per_year=52),
    Frequency.BIWEEKLY: FixedIntervalStrategy(days=14, periods_per_year=26),
    Frequency.MONTHLY: MonthlyStrategy(),
}


@dataclass(frozen=True, slots=True)
class ScheduledInstallment:
    number: int
    due_date: date
    amount: Decimal
    principal: Decimal
    interest: Decimal
    remaining_balance: Decimal


@dataclass(frozen=True, slots=True)
class PaymentSchedule:
    principal: Decimal
    apr: Decimal
    frequency: Frequency
    installments: tuple[ScheduledInstallment, ...]

    @property
    def total_interest(self) -> Decimal:
        return sum((i.interest for i in self.installments), Decimal("0.00"))

    @property
    def total_cost(self) -> Decimal:
        return sum((i.amount for i in self.installments), Decimal("0.00"))


class ScheduleCalculator:
    """Builds a payment schedule for a purchase.

    With a 0% APR the principal is split evenly and leftover cents go on the first
    installment, which is due at checkout. With interest, a standard amortizing payment is
    used and the final installment settles whatever balance remains after rounding.
    """

    def __init__(self, strategies: dict[Frequency, DueDateStrategy] | None = None) -> None:
        self.strategies = strategies or STRATEGIES

    def calculate(
        self,
        principal: Decimal,
        installment_count: int,
        apr: Decimal,
        frequency: Frequency,
        first_due: date,
    ) -> PaymentSchedule:
        self._validate(principal, installment_count, apr)
        strategy = self.strategies[frequency]
        principal = to_money(principal)

        if apr == 0:
            parts = self._even_split(principal, installment_count)
        else:
            rate = Decimal(apr) / Decimal(100) / Decimal(strategy.periods_per_year)
            parts = self._amortize(principal, installment_count, rate)

        amounts = [p + i for p, i in parts]
        installments = []
        remaining = sum(amounts, Decimal("0.00"))
        for index, ((part_principal, interest), amount) in enumerate(
            zip(parts, amounts, strict=True)
        ):
            remaining -= amount
            installments.append(
                ScheduledInstallment(
                    number=index + 1,
                    due_date=strategy.due_date(first_due, index),
                    amount=amount,
                    principal=part_principal,
                    interest=interest,
                    remaining_balance=remaining,
                )
            )
        return PaymentSchedule(
            principal=principal,
            apr=Decimal(apr),
            frequency=frequency,
            installments=tuple(installments),
        )

    @staticmethod
    def _validate(principal: Decimal, installment_count: int, apr: Decimal) -> None:
        if not MIN_PRINCIPAL <= principal <= MAX_PRINCIPAL:
            raise ValueError(f"principal must be between {MIN_PRINCIPAL} and {MAX_PRINCIPAL}")
        if principal != principal.quantize(CENT):
            raise ValueError("principal cannot have fractional cents")
        if not 1 <= installment_count <= MAX_INSTALLMENTS:
            raise ValueError(f"installment_count must be between 1 and {MAX_INSTALLMENTS}")
        if not Decimal(0) <= apr <= MAX_APR:
            raise ValueError(f"apr must be between 0 and {MAX_APR}")

    @staticmethod
    def _even_split(principal: Decimal, count: int) -> list[tuple[Decimal, Decimal]]:
        total_cents = int(principal / CENT)
        base_cents, remainder_cents = divmod(total_cents, count)
        zero = Decimal("0.00")
        parts = [(Decimal(base_cents) * CENT, zero) for _ in range(count)]
        parts[0] = (Decimal(base_cents + remainder_cents) * CENT, zero)
        return parts

    @staticmethod
    def _amortize(principal: Decimal, count: int, rate: Decimal) -> list[tuple[Decimal, Decimal]]:
        with localcontext() as ctx:
            ctx.prec = 34
            payment = to_money(principal * rate / (1 - (1 + rate) ** -count))

        parts = []
        balance = principal
        for number in range(1, count + 1):
            interest = to_money(balance * rate)
            part_principal = balance if number == count else min(payment - interest, balance)
            parts.append((part_principal, interest))
            balance -= part_principal
        return parts

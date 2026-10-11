"""Payment gateway abstraction plus a deterministic sandbox implementation.

The sandbox behaves like a real processor's test mode: magic payment-method tokens produce
specific outcomes, and charges are idempotent on the key the caller supplies, so retrying a
charge after a timeout can never bill the customer twice.
"""

import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal


class TransientGatewayError(Exception):
    """The processor could not give an answer (timeout, 5xx). Safe to retry."""


@dataclass(frozen=True, slots=True)
class ChargeResult:
    succeeded: bool
    reference: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None


class PaymentGateway(ABC):
    @abstractmethod
    def charge(
        self, amount: Decimal, currency: str, payment_method: str, idempotency_key: str
    ) -> ChargeResult:
        """Charge the payment method. Raises ``TransientGatewayError`` if the outcome is unknown."""


SANDBOX_PAYMENT_METHODS: dict[str, str] = {
    "pm_card_visa": "Always succeeds",
    "pm_card_mastercard": "Always succeeds",
    "pm_card_declined": "Declined with card_declined",
    "pm_card_insufficient_funds": "Declined with insufficient_funds",
    "pm_card_flaky": "Times out on the first attempt, then succeeds",
    "pm_card_processing_error": "Always times out (exhausts retries)",
}

_DECLINES = {
    "pm_card_declined": ("card_declined", "Your card was declined."),
    "pm_card_insufficient_funds": ("insufficient_funds", "Your card has insufficient funds."),
}


class SandboxGateway(PaymentGateway):
    def __init__(self, latency_s: float = 0.0) -> None:
        self.latency_s = latency_s
        self._lock = threading.Lock()
        self._results: dict[str, ChargeResult] = {}
        self._attempts: dict[str, int] = {}
        self.charges_made = 0

    def charge(
        self, amount: Decimal, currency: str, payment_method: str, idempotency_key: str
    ) -> ChargeResult:
        if self.latency_s:
            time.sleep(self.latency_s)
        with self._lock:
            if idempotency_key in self._results:
                return self._results[idempotency_key]
            attempt = self._attempts.get(idempotency_key, 0) + 1
            self._attempts[idempotency_key] = attempt

            if payment_method == "pm_card_processing_error" or (
                payment_method == "pm_card_flaky" and attempt == 1
            ):
                raise TransientGatewayError("Upstream processor timed out")

            if payment_method in _DECLINES:
                code, message = _DECLINES[payment_method]
                result = ChargeResult(False, failure_code=code, failure_message=message)
            elif payment_method in SANDBOX_PAYMENT_METHODS:
                self.charges_made += 1
                result = ChargeResult(True, reference=f"ch_sandbox_{uuid.uuid4().hex[:24]}")
            else:
                result = ChargeResult(
                    False,
                    failure_code="invalid_payment_method",
                    failure_message=f"Unknown sandbox payment method '{payment_method}'.",
                )
            self._results[idempotency_key] = result
            return result


class RetryPolicy:
    """Retries transient gateway failures with exponential backoff."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay_s: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.max_attempts = max_attempts
        self.base_delay_s = base_delay_s
        self._sleep = sleep

    def run[T](self, operation: Callable[[], T]) -> tuple[T, int]:
        """Return ``(result, attempts)``; re-raises the last transient error when exhausted."""
        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation(), attempt
            except TransientGatewayError:
                if attempt == self.max_attempts:
                    raise
                self._sleep(self.base_delay_s * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

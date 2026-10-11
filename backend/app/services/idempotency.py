"""Idempotency keys for unsafe requests.

A key is claimed with ``INSERT ... ON CONFLICT DO NOTHING`` against a unique ``(scope, key)``
constraint, so two concurrent requests can never both believe they own it. The winner does
the work and stores the response in the same transaction as its side effects; everyone else
either replays that response or is told the original request is still running.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.errors import IdempotencyInProgressError, IdempotencyKeyReuseError
from app.models import IdempotencyRecord, IdempotencyStatus


def fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Claimed:
    """The caller owns the key and must run the operation."""

    record_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class Replay:
    """The operation already finished; return the stored response verbatim."""

    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IdempotentResult:
    status_code: int
    body: dict[str, Any]
    replayed: bool


class IdempotencyService:
    def __init__(self, session_factory: sessionmaker[Session], lock_timeout_s: int) -> None:
        self.session_factory = session_factory
        self.lock_timeout = timedelta(seconds=lock_timeout_s)

    def begin(self, scope: str, key: str, request_hash: str) -> Claimed | Replay:
        now = datetime.now(UTC)
        with self.session_factory.begin() as session:
            inserted_id = session.execute(
                insert(IdempotencyRecord)
                .values(
                    id=uuid.uuid4(),
                    scope=scope,
                    key=key,
                    request_hash=request_hash,
                    status=IdempotencyStatus.IN_PROGRESS,
                    locked_at=now,
                    created_at=now,
                )
                .on_conflict_do_nothing(constraint="uq_idempotency_scope_key")
                .returning(IdempotencyRecord.id)
            ).scalar_one_or_none()
            if inserted_id is not None:
                return Claimed(inserted_id)

            record = session.execute(
                select(IdempotencyRecord)
                .where(IdempotencyRecord.scope == scope, IdempotencyRecord.key == key)
                .with_for_update()
            ).scalar_one()

            if record.request_hash != request_hash:
                raise IdempotencyKeyReuseError(
                    "This Idempotency-Key was already used with a different request body."
                )
            if record.status == IdempotencyStatus.COMPLETED:
                return Replay(record.response_status, record.response_body)
            if record.locked_at is None or now - record.locked_at > self.lock_timeout:
                # The previous owner crashed or gave up mid-flight. Take over and resume.
                record.locked_at = now
                return Claimed(record.id)
            raise IdempotencyInProgressError(
                "A request with this Idempotency-Key is still being processed."
            )

    @staticmethod
    def complete(
        session: Session, record_id: uuid.UUID, status_code: int, body: dict[str, Any]
    ) -> None:
        """Store the response. Call inside the transaction that commits the side effects."""
        session.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.id == record_id)
            .values(
                status=IdempotencyStatus.COMPLETED,
                response_status=status_code,
                response_body=body,
                completed_at=datetime.now(UTC),
                locked_at=None,
            )
        )

    def release(self, record_id: uuid.UUID) -> None:
        """Forget a key whose request failed before any side effect, so it can be reused."""
        with self.session_factory.begin() as session:
            session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.id == record_id))

    def unlock(self, record_id: uuid.UUID) -> None:
        """Keep the key but let the next request with it resume the interrupted work."""
        with self.session_factory.begin() as session:
            session.execute(
                update(IdempotencyRecord)
                .where(IdempotencyRecord.id == record_id)
                .values(locked_at=None)
            )

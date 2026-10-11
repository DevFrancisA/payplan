import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.config import Settings
from app.db import Database
from app.main import create_app
from app.services.gateway import RetryPolicy, SandboxGateway
from app.services.idempotency import IdempotencyService
from app.services.payments import PaymentService
from app.services.plans import PlanService

TEST_DATABASE_URL = os.environ.get(
    "PAYPLAN_TEST_DATABASE_URL",
    "postgresql+psycopg://payplan:payplan@localhost:5433/payplan_test",
)
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url=TEST_DATABASE_URL,
        gateway_latency_ms=0,
        gateway_max_attempts=3,
        gateway_retry_base_delay_s=0,
        idempotency_lock_timeout_s=30,
        log_level="WARNING",
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_schema(settings: Settings) -> None:
    """Rebuild the schema from the Alembic migrations, so tests also verify them."""
    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    config = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    config.attributes["database_url"] = settings.database_url
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def database(settings: Settings, migrated_schema: None) -> Iterator[Database]:
    db = Database(settings)
    yield db
    db.dispose()


@pytest.fixture(autouse=True)
def clean_tables(database: Database) -> None:
    with database.engine.begin() as conn:
        conn.execute(text("TRUNCATE plans, installments, payments, idempotency_keys CASCADE"))


@pytest.fixture
def gateway() -> SandboxGateway:
    return SandboxGateway()


@pytest.fixture
def client(settings: Settings, gateway: SandboxGateway) -> Iterator[TestClient]:
    with TestClient(create_app(settings, gateway)) as test_client:
        yield test_client


@pytest.fixture
def idempotency(database: Database, settings: Settings) -> IdempotencyService:
    return IdempotencyService(database.session_factory, settings.idempotency_lock_timeout_s)


@pytest.fixture
def plan_service(database: Database, idempotency: IdempotencyService) -> PlanService:
    return PlanService(database.session_factory, idempotency)


@pytest.fixture
def payment_service(
    database: Database, gateway: SandboxGateway, idempotency: IdempotencyService
) -> PaymentService:
    return PaymentService(
        database.session_factory, gateway, RetryPolicy(3, 0, sleep=lambda _: None), idempotency
    )


def new_key() -> str:
    return str(uuid.uuid4())


PLAN_BODY = {
    "principal": "1200.00",
    "installment_count": 4,
    "frequency": "biweekly",
    "apr": "0",
    "first_due_date": "2026-10-01",
}


@pytest.fixture
def plan(client: TestClient) -> dict:
    response = client.post("/api/v1/plans", json=PLAN_BODY, headers={"Idempotency-Key": new_key()})
    assert response.status_code == 201, response.text
    return response.json()


def pay(client: TestClient, plan_id: str, number: int, method: str = "pm_card_visa", key=None):
    return client.post(
        f"/api/v1/plans/{plan_id}/installments/{number}/payments",
        json={"payment_method": method},
        headers={"Idempotency-Key": key or new_key()},
    )

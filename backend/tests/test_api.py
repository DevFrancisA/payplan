import io
import json

import pytest
from sqlalchemy import func, select

from app.models import Installment, Plan
from app.observability import metrics
from tests.conftest import PLAN_BODY, new_key


def test_quote_returns_schedule_and_totals(client, database):
    response = client.post(
        "/api/v1/quotes",
        json={**PLAN_BODY, "apr": "15", "frequency": "monthly", "installment_count": 6},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["principal"] == "1200.00"
    assert body["installment_count"] == 6
    assert [i["due_date"] for i in body["installments"]][:3] == [
        "2026-10-01",
        "2026-11-01",
        "2026-12-01",
    ]
    assert body["total_cost"] == "1253.04"
    assert body["installments"][-1]["remaining_balance"] == "0.00"
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Plan)) == 0, "quotes are not saved"


@pytest.mark.parametrize(
    "override",
    [{"installment_count": 0}, {"principal": "0.00"}, {"apr": "50"}],
)
def test_quote_rejects_invalid_terms(client, override):
    response = client.post("/api/v1/quotes", json={**PLAN_BODY, **override})
    assert response.status_code == 422


def test_openapi_documents_endpoints_and_idempotency_header(client):
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "PayPlan API"
    pay = spec["paths"]["/api/v1/plans/{plan_id}/installments/{number}/payments"]["post"]
    header = next(p for p in pay["parameters"] if p["name"] == "Idempotency-Key")
    assert header["in"] == "header" and header["required"] is True
    assert {"201", "404", "409", "422"} <= set(pay["responses"])
    assert "/api/v1/quotes" in spec["paths"]


def test_health_probes_and_request_metrics(client):
    stream = io.StringIO()
    metrics.configure(True, "PayPlan", "payplan-api", stream=stream)
    try:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json() == {"status": "ready"}
        response = client.get("/api/v1/plans/00000000-0000-0000-0000-000000000000")
    finally:
        metrics.configure(False, "PayPlan", "payplan-api")

    assert response.status_code == 404
    assert response.headers["X-Request-ID"]
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert len(records) == 1, "health checks should not be recorded as traffic"
    emf = records[0]
    assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "PayPlan"
    assert emf["route"] == "GET /api/v1/plans/{plan_id}"
    assert emf["ClientErrors"] == 1 and emf["ServerErrors"] == 0
    assert emf["Latency"] >= 0


def test_create_plan_persists_schedule(client, database):
    response = client.post("/api/v1/plans", json=PLAN_BODY, headers={"Idempotency-Key": new_key()})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    assert body["remaining_balance"] == "1200.00"
    assert [i["amount"] for i in body["installments"]] == ["300.00"] * 4

    fetched = client.get(f"/api/v1/plans/{body['id']}").json()
    assert fetched == body
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Installment)) == 4


def test_create_plan_replays_for_same_key(client, database):
    key = new_key()
    first = client.post("/api/v1/plans", json=PLAN_BODY, headers={"Idempotency-Key": key})
    second = client.post("/api/v1/plans", json=PLAN_BODY, headers={"Idempotency-Key": key})
    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Plan)) == 1


def test_create_plan_rejects_key_reuse_with_different_body(client):
    key = new_key()
    client.post("/api/v1/plans", json=PLAN_BODY, headers={"Idempotency-Key": key})
    response = client.post(
        "/api/v1/plans",
        json={**PLAN_BODY, "principal": "1300.00"},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_reused"


def test_create_plan_requires_idempotency_key(client):
    assert client.post("/api/v1/plans", json=PLAN_BODY).status_code == 422
    short = client.post("/api/v1/plans", json=PLAN_BODY, headers={"Idempotency-Key": "abc"})
    assert short.status_code == 422

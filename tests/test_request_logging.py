"""Correlated request logs expose operational metadata, never ticket contents."""

import json
import logging
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import llm_client, main, request_logging
from app.schemas import LLMClassificationResult, TicketRequest

TICKET = {
    "ticket_id": "private-ticket-id",
    "subject": "private-subject-marker",
    "description": "private-description-marker with confidential information",
}
CLASSIFICATION = LLMClassificationResult(
    category="other",
    priority="low",
    summary="private-summary-marker",
    suggested_action="private-action-marker",
)


def request_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "app.requests"]


@pytest.fixture(autouse=True)
def classifier(monkeypatch: pytest.MonkeyPatch) -> Mock:
    def classify(ticket: TicketRequest) -> LLMClassificationResult:
        request_logging.record_model("test-model")
        return CLASSIFICATION

    mock = Mock(side_effect=classify)
    monkeypatch.setattr(llm_client, "classify_ticket", mock)
    return mock


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_success_log_correlates_response_and_excludes_sensitive_data(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        request_logging, "perf_counter", Mock(side_effect=[100, 100.125])
    )
    response = client.post(
        "/api/v1/triage?token=private-query-marker",
        json=TICKET,
        headers={
            "X-Request-ID": "request-123",
            "Authorization": "Bearer private-token",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-123"
    records = request_records(caplog)
    assert len(records) == 1
    assert json.loads(records[0].getMessage()) == {
        "request_id": "request-123",
        "endpoint": "/api/v1/triage",
        "status_code": 200,
        "latency_ms": 125,
        "model": "test-model",
        "error_type": None,
    }
    assert records[0].levelno == logging.INFO
    assert records[0].exc_info is None
    assert "private-" not in records[0].getMessage()


@pytest.mark.parametrize("supplied_id", [None, "", "x" * 65, "bad id", "bad\r\nlog"])
def test_missing_or_unsafe_ids_are_replaced_with_unique_ids(
    client: TestClient, caplog: pytest.LogCaptureFixture, supplied_id: str | None
) -> None:
    headers = {} if supplied_id is None else {"X-Request-ID": supplied_id}
    first = client.get("/health", headers=headers)
    second = client.get("/health", headers=headers)

    ids = [first.headers["X-Request-ID"], second.headers["X-Request-ID"]]
    assert ids[0] != ids[1]
    assert all(UUID(value).version == 4 for value in ids)
    logs = [json.loads(record.getMessage()) for record in request_records(caplog)]
    assert [log["request_id"] for log in logs] == ids
    assert all(log["model"] is None and log["error_type"] is None for log in logs)


@pytest.mark.parametrize(
    "error,status",
    [
        (llm_client.LLMClientError("private-provider-secret"), 503),
        (llm_client.LLMTimeoutError("private-timeout-secret"), 504),
        (llm_client.LLMResponseError("private-model-output"), 503),
        (RuntimeError("private-subject-marker and private-secret"), 500),
    ],
)
def test_failure_logs_safe_type_and_matching_id_once(
    client: TestClient,
    classifier: Mock,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    status: int,
) -> None:
    def fail(ticket: TicketRequest) -> None:
        request_logging.record_model("failed-model")
        raise error

    classifier.side_effect = fail
    response = client.post("/api/v1/triage", json=TICKET)

    assert response.status_code == status
    records = request_records(caplog)
    assert len(records) == 1
    log = json.loads(records[0].getMessage())
    assert log["request_id"] == response.headers["X-Request-ID"]
    assert log["endpoint"] == "/api/v1/triage"
    assert log["status_code"] == status
    assert log["error_type"] == type(error).__name__
    assert log["model"] == "failed-model"
    assert log["latency_ms"] >= 0
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is None
    assert "private-" not in records[0].getMessage()

    # An error's metadata must not leak into a later request.
    client.get("/health")
    health_log = json.loads(request_records(caplog)[-1].getMessage())
    assert health_log["model"] is None
    assert health_log["error_type"] is None


def test_invalid_input_is_logged_without_body_or_llm_call(
    client: TestClient, classifier: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    response = client.post("/api/v1/triage", json={"subject": TICKET["subject"]})

    assert response.status_code == 422
    classifier.assert_not_called()
    records = request_records(caplog)
    assert len(records) == 1
    log = json.loads(records[0].getMessage())
    assert log["status_code"] == 422
    assert log["error_type"] == "RequestValidationError"
    assert log["model"] is None
    assert log["request_id"] == response.headers["X-Request-ID"]
    assert "private-" not in records[0].getMessage()


def test_unmatched_url_is_not_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    response = client.get("/private-path-secret?token=private-query-secret")

    assert response.status_code == 404
    records = request_records(caplog)
    assert len(records) == 1
    log = json.loads(records[0].getMessage())
    assert log["endpoint"] == "<unmatched>"
    assert log["status_code"] == 404
    assert log["request_id"] == response.headers["X-Request-ID"]
    assert "private-" not in records[0].getMessage()


def test_concurrent_requests_keep_model_and_id_isolated(
    client: TestClient, classifier: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    barrier = Barrier(2)

    def classify(ticket: TicketRequest) -> LLMClassificationResult:
        request_logging.record_model(f"model-{ticket.ticket_id}")
        barrier.wait(timeout=5)
        return CLASSIFICATION

    def send(request_id: str) -> None:
        response = client.post(
            "/api/v1/triage",
            json={**TICKET, "ticket_id": request_id},
            headers={"X-Request-ID": request_id},
        )
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == request_id

    classifier.side_effect = classify
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(send, ["first", "second"]))

    logs = [json.loads(record.getMessage()) for record in request_records(caplog)]
    assert len(logs) == 2
    assert {log["request_id"]: log["model"] for log in logs} == {
        "first": "model-first",
        "second": "model-second",
    }

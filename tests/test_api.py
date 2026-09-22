"""HTTP contract tests for the basic application; no provider calls are made."""

from collections.abc import Iterator

import pytest
from fastapi.exceptions import ResponseValidationError
from fastapi.testclient import TestClient

from app import main
from app.schemas import TriageResponse

TICKET = {
    "subject": "VPN connection problem",
    "description": "I cannot connect to the corporate VPN after changing my password.",
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with TestClient(main.app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "id_fields", [{}, {"ticket_id": None}, {"ticket_id": "TCK-1001"}]
)
def test_triage_returns_valid_mock_response(
    client: TestClient, id_fields: dict[str, str | None]
) -> None:
    response = client.post("/api/v1/triage", json={**TICKET, **id_fields})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "ticket_id": id_fields.get("ticket_id"),
        "category": "other",
        "department": "service_desk",
        "priority": "medium",
        "summary": "Mock triage result; ticket has not been classified.",
        "suggested_action": "Review the ticket manually.",
        "needs_human_review": True,
    }
    TriageResponse.model_validate(response.json())


def test_triage_returns_same_mock_for_different_ticket_content(
    client: TestClient,
) -> None:
    first = client.post("/api/v1/triage", json=TICKET)
    second = client.post(
        "/api/v1/triage",
        json={
            "subject": "Printer problem",
            "description": "The printer prints blank pages.",
        },
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_triage_preserves_validated_ticket_id(client: TestClient) -> None:
    response = client.post(
        "/api/v1/triage", json={**TICKET, "ticket_id": "  TCK-1001  "}
    )

    assert response.status_code == 200
    assert response.json()["ticket_id"] == "TCK-1001"


@pytest.mark.parametrize(
    "payload,field",
    [
        ({"description": TICKET["description"]}, "subject"),
        ({"subject": TICKET["subject"]}, "description"),
        ({**TICKET, "subject": ""}, "subject"),
        ({**TICKET, "subject": " \t "}, "subject"),
        ({**TICKET, "subject": "x" * 201}, "subject"),
        ({**TICKET, "description": "short"}, "description"),
        ({**TICKET, "description": "x" * 5001}, "description"),
        ({**TICKET, "description": None}, "description"),
        ({**TICKET, "ticket_id": "x" * 101}, "ticket_id"),
        ({**TICKET, "ticket_id": 123}, "ticket_id"),
        ({**TICKET, "priority": "critical"}, "priority"),
    ],
)
def test_triage_rejects_invalid_tickets(
    client: TestClient, payload: dict[str, object], field: str
) -> None:
    response = client.post("/api/v1/triage", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]


@pytest.mark.parametrize("body", ["", "{invalid json", "null", "[]"])
def test_triage_rejects_invalid_request_bodies(client: TestClient, body: str) -> None:
    response = client.post(
        "/api/v1/triage", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


def test_triage_enforces_response_schema(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bypass construction validation to exercise FastAPI's response validation.
    monkeypatch.setattr(
        main, "TriageResponse", lambda **fields: {**fields, "priority": "invalid"}
    )

    with pytest.raises(ResponseValidationError):
        client.post("/api/v1/triage", json=TICKET)


def test_swagger_docs(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "SwaggerUIBundle" in response.text
    assert "/openapi.json" in response.text


def test_openapi_documents_existing_request_and_response_schemas(
    client: TestClient,
) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "get" in schema["paths"]["/health"]
    operation = schema["paths"]["/api/v1/triage"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TicketRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TriageResponse"
    }
    assert "422" in operation["responses"]

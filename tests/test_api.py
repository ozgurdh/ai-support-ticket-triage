"""HTTP contract tests for the basic application; no provider calls are made."""

from collections.abc import Iterator
from unittest.mock import Mock, call

import pytest
from fastapi.exceptions import ResponseValidationError
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import llm_client, main
from app.schemas import LLMClassificationResult, TicketRequest, TriageResponse

TICKET = {
    "subject": "VPN connection problem",
    "description": "I cannot connect to the corporate VPN after changing my password.",
}


@pytest.fixture(autouse=True)
def classifier(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock = Mock(
        spec=llm_client.classify_ticket,
        return_value=LLMClassificationResult(
            category="access_authentication",
            priority="high",
            summary="User cannot connect to the VPN after a password change.",
            suggested_action="Verify credential synchronization.",
        ),
    )
    monkeypatch.setattr(llm_client, "classify_ticket", mock)
    return mock


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with TestClient(main.app) as test_client:
        yield test_client


def test_health(client: TestClient, classifier: Mock) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    classifier.assert_not_called()


@pytest.mark.parametrize(
    "id_fields", [{}, {"ticket_id": None}, {"ticket_id": "TCK-1001"}]
)
def test_triage_returns_service_response(
    client: TestClient, classifier: Mock, id_fields: dict[str, str | None]
) -> None:
    response = client.post("/api/v1/triage", json={**TICKET, **id_fields})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "ticket_id": id_fields.get("ticket_id"),
        "category": "access_authentication",
        "department": "identity_access",
        "priority": "high",
        "summary": "User cannot connect to the VPN after a password change.",
        "suggested_action": "Verify credential synchronization.",
        "needs_human_review": False,
    }
    TriageResponse.model_validate(response.json())
    classifier.assert_called_once_with(TicketRequest(**TICKET, **id_fields))


def test_triage_uses_each_classification_result(
    client: TestClient,
    classifier: Mock,
) -> None:
    printer_ticket = {
        "subject": "Printer problem",
        "description": "The printer prints blank pages.",
    }
    printer_result = LLMClassificationResult(
        category="hardware_device",
        priority="medium",
        summary="Printer prints blank pages.",
        suggested_action="Check the ink level.",
    )
    classifier.side_effect = [classifier.return_value, printer_result]
    first = client.post("/api/v1/triage", json=TICKET)
    second = client.post("/api/v1/triage", json=printer_ticket)

    assert first.status_code == second.status_code == 200
    assert first.json()["department"] == "identity_access"
    assert second.json() == {
        **printer_result.model_dump(mode="json"),
        "ticket_id": None,
        "department": "service_desk",
        "needs_human_review": False,
    }
    assert classifier.call_args_list == [
        call(TicketRequest(**TICKET)),
        call(TicketRequest(**printer_ticket)),
    ]


@pytest.mark.parametrize(
    "category,priority,department",
    [
        ("security_incident", "low", "security"),
        ("other", "medium", "service_desk"),
        ("network_connectivity", "critical", "infrastructure_network"),
    ],
)
def test_triage_applies_human_review_rules(
    client: TestClient, classifier: Mock, category: str, priority: str, department: str
) -> None:
    classifier.return_value = LLMClassificationResult(
        category=category,
        priority=priority,
        summary="Ticket requires review.",
        suggested_action="Review the reported issue.",
    )

    response = client.post("/api/v1/triage", json=TICKET)

    assert response.status_code == 200
    assert response.json()["category"] == category
    assert response.json()["priority"] == priority
    assert response.json()["department"] == department
    assert response.json()["needs_human_review"] is True
    classifier.assert_called_once()


def test_triage_preserves_validated_ticket_id(
    client: TestClient, classifier: Mock
) -> None:
    response = client.post(
        "/api/v1/triage", json={**TICKET, "ticket_id": "  TCK-1001  "}
    )

    assert response.status_code == 200
    assert response.json()["ticket_id"] == "TCK-1001"
    classifier.assert_called_once_with(TicketRequest(**TICKET, ticket_id="TCK-1001"))


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
    client: TestClient, classifier: Mock, payload: dict[str, object], field: str
) -> None:
    response = client.post("/api/v1/triage", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    classifier.assert_not_called()


@pytest.mark.parametrize("body", ["", "{invalid json", "null", "[]"])
def test_triage_rejects_invalid_request_bodies(
    client: TestClient, classifier: Mock, body: str
) -> None:
    response = client.post(
        "/api/v1/triage", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    classifier.assert_not_called()


def test_triage_enforces_response_schema(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate an invalid service result to exercise FastAPI's response validation.
    monkeypatch.setattr(
        main.service, "triage_ticket", Mock(return_value={"priority": "invalid"})
    )

    with pytest.raises(ResponseValidationError):
        client.post("/api/v1/triage", json=TICKET)


@pytest.mark.parametrize(
    "error,status,detail",
    [
        (
            llm_client.LLMClientError("Private provider details"),
            503,
            "Provider unavailable.",
        ),
        (
            llm_client.LLMResponseError("Private model output"),
            503,
            "Provider unavailable.",
        ),
        (
            llm_client.LLMTimeoutError("Private timeout details"),
            504,
            "Provider request timed out.",
        ),
    ],
)
def test_provider_failures_return_safe_http_errors(
    client: TestClient, classifier: Mock, error: Exception, status: int, detail: str
) -> None:
    classifier.side_effect = error

    response = client.post("/api/v1/triage", json=TICKET)

    assert response.status_code == status
    assert response.json() == {"detail": detail}
    classifier.assert_called_once()


def test_unexpected_error_returns_safe_500(classifier: Mock) -> None:
    classifier.side_effect = RuntimeError("Private implementation details and secret")
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/triage", json=TICKET)

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    classifier.assert_called_once()


def test_local_validation_error_returns_500_not_request_422(classifier: Mock) -> None:
    with pytest.raises(ValidationError) as error:
        LLMClassificationResult.model_validate({"summary": "Private model output"})
    classifier.side_effect = error.value
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/triage", json=TICKET)

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    classifier.assert_called_once()


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
    assert {"422", "500", "503", "504"} <= operation["responses"].keys()

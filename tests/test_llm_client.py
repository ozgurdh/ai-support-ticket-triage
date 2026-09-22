"""Exercise the real SDK parser against an in-memory HTTP mock, never the API."""

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI
from pydantic import ValidationError

from app import llm_client, main
from app.config import Settings
from app.prompt import build_messages
from app.schemas import LLMClassificationResult, TicketRequest

CLASSIFICATION = {
    "category": "access_authentication",
    "priority": "high",
    "summary": "User cannot connect to the VPN after a password change.",
    "suggested_action": "Verify credential synchronization.",
}
TICKET = TicketRequest(
    ticket_id="PRIVATE-ID",
    subject="VPN problem",
    description="I cannot connect to the VPN after changing my password.",
)


def response_body(
    text: str = json.dumps(CLASSIFICATION), status: str = "completed"
) -> dict[str, object]:
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "model": "test-model",
        "status": status,
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
    }


@pytest.fixture
def provider() -> Mock:
    return Mock(return_value=httpx.Response(200, json=response_body()))


@pytest.fixture(autouse=True)
def retry_sleep(monkeypatch: pytest.MonkeyPatch) -> Mock:
    sleeper = Mock()
    monkeypatch.setattr(llm_client, "sleep", sleeper)
    return sleeper


@pytest.fixture(autouse=True)
def sdk_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provider: Mock
) -> Iterator[Mock]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "7.5")
    clients = []

    def create_client(**kwargs: object) -> OpenAI:
        client = OpenAI(
            **kwargs,
            base_url="https://provider.invalid/v1",
            http_client=httpx.Client(transport=httpx.MockTransport(provider)),
        )
        clients.append(client)
        return client

    factory = Mock(side_effect=create_client)
    monkeypatch.setattr(llm_client, "OpenAI", factory)
    yield factory
    assert all(client.is_closed() for client in clients)


def test_classifies_using_configured_sdk_and_structured_schema(
    provider: Mock, sdk_factory: Mock
) -> None:
    result = llm_client.classify_ticket(TICKET)

    assert isinstance(result, LLMClassificationResult)
    assert result.model_dump(mode="json") == CLASSIFICATION
    sdk_factory.assert_called_once_with(
        api_key="test-only-key", timeout=7.5, max_retries=0
    )
    provider.assert_called_once()
    request = provider.call_args.args[0]
    assert request.url.path == "/v1/responses"
    assert request.method == "POST"
    assert request.extensions["timeout"]["read"] == 7.5
    payload = json.loads(request.content)
    assert payload["model"] == "test-model"
    assert payload["input"] == build_messages(TICKET)
    assert payload["store"] is False
    output_format = payload["text"]["format"]
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True
    assert output_format["schema"] == LLMClassificationResult.model_json_schema()
    assert "PRIVATE-ID" not in request.content.decode()


def test_accepts_explicit_settings(provider: Mock, sdk_factory: Mock) -> None:
    settings = Settings(
        openai_api_key="another-test-key",
        openai_model="another-model",
        openai_timeout_seconds=15,
    )

    llm_client.classify_ticket(TICKET, settings)

    sdk_factory.assert_called_once_with(
        api_key="another-test-key", timeout=15, max_retries=0
    )
    assert json.loads(provider.call_args.args[0].content)["model"] == "another-model"


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        "{}",
        json.dumps({**CLASSIFICATION, "category": "unknown"}),
        json.dumps({**CLASSIFICATION, "priority": "urgent"}),
        json.dumps({**CLASSIFICATION, "summary": " "}),
        json.dumps({**CLASSIFICATION, "department": "security"}),
    ],
)
def test_invalid_structured_output_exhausts_retry(
    provider: Mock, retry_sleep: Mock, text: str
) -> None:
    provider.return_value = httpx.Response(200, json=response_body(text))

    with pytest.raises(llm_client.LLMResponseError, match="invalid classification"):
        llm_client.classify_ticket(TICKET)

    assert provider.call_count == 2
    retry_sleep.assert_called_once_with(0.5)


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled"])
def test_non_completed_response_is_rejected(provider: Mock, status: str) -> None:
    provider.return_value = httpx.Response(200, json=response_body(status=status))

    with pytest.raises(llm_client.LLMResponseError):
        llm_client.classify_ticket(TICKET)

    provider.assert_called_once()


@pytest.mark.parametrize("refusal", [False, True])
def test_absent_classification_or_refusal_is_rejected(
    provider: Mock, refusal: bool
) -> None:
    body = response_body()
    if refusal:
        body["output"][0]["content"] = [
            {"type": "refusal", "refusal": "Private provider refusal details"}
        ]
    else:
        body["output"] = []
    provider.return_value = httpx.Response(200, json=body)

    with pytest.raises(llm_client.LLMResponseError) as error:
        llm_client.classify_ticket(TICKET)

    assert "Private provider" not in str(error.value)
    assert provider.call_count == (1 if refusal else 2)


@pytest.mark.parametrize(
    "failure,expected",
    [
        (httpx.ReadTimeout("Private timeout details"), llm_client.LLMTimeoutError),
        (httpx.ConnectError("Private connection details"), llm_client.LLMClientError),
    ],
)
def test_transport_failure_exhausts_retry(
    provider: Mock, retry_sleep: Mock, failure: Exception, expected: type[Exception]
) -> None:
    provider.side_effect = failure

    with pytest.raises(expected) as error:
        llm_client.classify_ticket(TICKET)

    assert "Private" not in str(error.value)
    assert provider.call_count == 2
    retry_sleep.assert_called_once_with(0.5)


@pytest.mark.parametrize(
    "status,attempts",
    [
        (400, 1),
        (401, 1),
        (403, 1),
        (404, 1),
        (422, 1),
        (409, 2),
        (429, 2),
        (500, 2),
        (502, 2),
        (503, 2),
    ],
)
def test_provider_error_is_wrapped_after_allowed_attempts(
    provider: Mock, retry_sleep: Mock, status: int, attempts: int
) -> None:
    provider.return_value = httpx.Response(
        status, json={"error": {"message": "Private provider details", "type": "error"}}
    )

    with pytest.raises(llm_client.LLMClientError, match="^Provider request failed\\.$"):
        llm_client.classify_ticket(TICKET)

    assert provider.call_count == attempts
    assert retry_sleep.call_count == attempts - 1


@pytest.mark.parametrize("status", [408, 504])
def test_provider_http_timeout_exhausts_retry(provider: Mock, status: int) -> None:
    provider.return_value = httpx.Response(
        status, json={"error": {"message": "Private"}}
    )

    with pytest.raises(
        llm_client.LLMTimeoutError, match="^Provider request timed out\\.$"
    ):
        llm_client.classify_ticket(TICKET)

    assert provider.call_count == 2


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("Private"),
        httpx.ConnectError("Private"),
        httpx.Response(429, json={"error": {"message": "Rate limited"}}),
        httpx.Response(503, json={"error": {"message": "Unavailable"}}),
        httpx.Response(200, json=response_body("not JSON")),
        httpx.Response(200, json={**response_body(), "output": []}),
    ],
)
def test_transient_failure_recovers_on_second_attempt(
    provider: Mock,
    sdk_factory: Mock,
    retry_sleep: Mock,
    failure: httpx.Response | Exception,
) -> None:
    provider.side_effect = [failure, httpx.Response(200, json=response_body())]

    result = llm_client.classify_ticket(TICKET)

    assert result.model_dump(mode="json") == CLASSIFICATION
    assert provider.call_count == 2
    sdk_factory.assert_called_once()
    retry_sleep.assert_called_once_with(0.5)
    first, second = [call.args[0] for call in provider.call_args_list]
    assert first.content == second.content


def test_permanent_failure_after_timeout_stops_retry(provider: Mock) -> None:
    provider.side_effect = [
        httpx.ReadTimeout("Private timeout"),
        httpx.Response(401, json={"error": {"message": "Private credentials"}}),
        httpx.Response(200, json=response_body()),
    ]

    with pytest.raises(llm_client.LLMClientError, match="^Provider request failed\\.$"):
        llm_client.classify_ticket(TICKET)

    assert provider.call_count == 2


@pytest.mark.parametrize(
    "code",
    [
        "insufficient_quota",
        "credit_balance_exhausted",
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
        "organization_usage_limit_exceeded",
    ],
)
def test_quota_failure_is_not_retried(
    provider: Mock, retry_sleep: Mock, code: str
) -> None:
    provider.return_value = httpx.Response(
        429, json={"error": {"message": "Private billing details", "code": code}}
    )

    with pytest.raises(llm_client.LLMClientError):
        llm_client.classify_ticket(TICKET)

    provider.assert_called_once()
    retry_sleep.assert_not_called()


@pytest.mark.parametrize(
    "headers",
    [{"retry-after": "60"}, {"retry-after-ms": "60000"}, {"x-should-retry": "false"}],
)
def test_server_retry_restrictions_are_respected(
    provider: Mock, retry_sleep: Mock, headers: dict[str, str]
) -> None:
    provider.return_value = httpx.Response(
        429, headers=headers, json={"error": {"message": "Private"}}
    )

    with pytest.raises(llm_client.LLMClientError):
        llm_client.classify_ticket(TICKET)

    provider.assert_called_once()
    retry_sleep.assert_not_called()


def test_local_result_validation_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, retry_sleep: Mock
) -> None:
    request = Mock(return_value={**CLASSIFICATION, "category": "invalid"})
    monkeypatch.setattr(llm_client, "_request_classification", request)

    with pytest.raises(ValidationError):
        llm_client.classify_ticket(TICKET)

    request.assert_called_once()
    retry_sleep.assert_not_called()


def test_local_prompt_validation_makes_no_request(
    monkeypatch: pytest.MonkeyPatch,
    sdk_factory: Mock,
    provider: Mock,
    retry_sleep: Mock,
) -> None:
    with pytest.raises(ValidationError) as error:
        TicketRequest.model_validate({})
    monkeypatch.setattr(llm_client, "build_messages", Mock(side_effect=error.value))

    with pytest.raises(ValidationError):
        llm_client.classify_ticket(TICKET)

    sdk_factory.assert_not_called()
    provider.assert_not_called()
    retry_sleep.assert_not_called()


def test_configuration_failure_makes_no_request(
    monkeypatch: pytest.MonkeyPatch, sdk_factory: Mock, provider: Mock
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")

    with pytest.raises(ValidationError):
        llm_client.classify_ticket(TICKET)

    sdk_factory.assert_not_called()
    provider.assert_not_called()


@pytest.mark.parametrize(
    "failure,status,detail",
    [
        (httpx.ReadTimeout("Private"), 504, "Provider request timed out."),
        (
            httpx.Response(503, json={"error": {"message": "Private"}}),
            503,
            "Provider unavailable.",
        ),
        (
            httpx.Response(200, json=response_body("Private invalid JSON")),
            503,
            "Provider unavailable.",
        ),
    ],
)
def test_exhausted_provider_failure_reaches_http_response(
    provider: Mock,
    failure: httpx.Response | Exception,
    status: int,
    detail: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider.side_effect = [failure, failure]
    with TestClient(main.app) as client:
        response = client.post("/api/v1/triage", json=TICKET.model_dump())

    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert provider.call_count == 2
    logs = [record for record in caplog.records if record.name == "app.requests"]
    assert len(logs) == 1  # Retries belong to the same HTTP request.
    metadata = json.loads(logs[0].getMessage())
    assert metadata["request_id"] == response.headers["X-Request-ID"]
    assert metadata["model"] == "test-model"
    assert metadata["status_code"] == status
    assert metadata["error_type"] is not None
    assert "Private" not in logs[0].getMessage()
    assert "test-only-key" not in logs[0].getMessage()


def test_missing_configuration_returns_safe_500_without_provider_call(
    monkeypatch: pytest.MonkeyPatch,
    provider: Mock,
    sdk_factory: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/triage", json=TICKET.model_dump())

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    provider.assert_not_called()
    sdk_factory.assert_not_called()
    logs = [record for record in caplog.records if record.name == "app.requests"]
    assert len(logs) == 1
    metadata = json.loads(logs[0].getMessage())
    assert metadata["request_id"] == response.headers["X-Request-ID"]
    assert metadata["model"] is None
    assert metadata["error_type"] == "ValidationError"
    assert metadata["status_code"] == 500


def test_success_log_uses_model_loaded_by_client(
    provider: Mock, caplog: pytest.LogCaptureFixture
) -> None:
    with TestClient(main.app) as client:
        response = client.post("/api/v1/triage", json=TICKET.model_dump())

    assert response.status_code == 200
    provider.assert_called_once()
    logs = [record for record in caplog.records if record.name == "app.requests"]
    assert len(logs) == 1
    metadata = json.loads(logs[0].getMessage())
    assert metadata["model"] == "test-model"
    assert metadata["request_id"] == response.headers["X-Request-ID"]
    assert metadata["error_type"] is None
    for sensitive in (
        TICKET.subject,
        TICKET.description,
        TICKET.ticket_id,
        "test-only-key",
    ):
        assert sensitive not in logs[0].getMessage()

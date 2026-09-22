"""Exercise the real SDK parser against an in-memory HTTP mock, never the API."""

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from openai import OpenAI
from pydantic import ValidationError

from app import llm_client
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
def test_invalid_structured_output_is_rejected(provider: Mock, text: str) -> None:
    provider.return_value = httpx.Response(200, json=response_body(text))

    with pytest.raises(llm_client.LLMResponseError, match="invalid classification"):
        llm_client.classify_ticket(TICKET)

    provider.assert_called_once()


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled"])
def test_non_completed_response_is_rejected(provider: Mock, status: str) -> None:
    provider.return_value = httpx.Response(200, json=response_body(status=status))

    with pytest.raises(llm_client.LLMResponseError):
        llm_client.classify_ticket(TICKET)


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
    provider.assert_called_once()


@pytest.mark.parametrize(
    "failure,expected",
    [
        (httpx.ReadTimeout("Private timeout details"), llm_client.LLMTimeoutError),
        (httpx.ConnectError("Private connection details"), llm_client.LLMClientError),
    ],
)
def test_transport_failure_is_wrapped_without_retry(
    provider: Mock, failure: Exception, expected: type[Exception]
) -> None:
    provider.side_effect = failure

    with pytest.raises(expected) as error:
        llm_client.classify_ticket(TICKET)

    assert "Private" not in str(error.value)
    provider.assert_called_once()


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
def test_provider_error_is_wrapped_without_retry(provider: Mock, status: int) -> None:
    provider.return_value = httpx.Response(
        status, json={"error": {"message": "Private provider details", "type": "error"}}
    )

    with pytest.raises(llm_client.LLMClientError, match="^Provider request failed\\.$"):
        llm_client.classify_ticket(TICKET)

    provider.assert_called_once()


def test_configuration_failure_makes_no_request(
    monkeypatch: pytest.MonkeyPatch, sdk_factory: Mock, provider: Mock
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")

    with pytest.raises(ValidationError):
        llm_client.classify_ticket(TICKET)

    sdk_factory.assert_not_called()
    provider.assert_not_called()

"""Business-rule tests with the LLM client replaced by a mock."""

from unittest.mock import Mock

import pytest

from app import llm_client, service
from app.enums import TicketPriority
from app.schemas import LLMClassificationResult, TicketRequest, TriageResponse


@pytest.fixture(autouse=True)
def classifier(monkeypatch: pytest.MonkeyPatch) -> Mock:
    mock = Mock(spec=llm_client.classify_ticket)
    monkeypatch.setattr(llm_client, "classify_ticket", mock)
    return mock


@pytest.mark.parametrize(
    "category,department,reviews",
    [
        ("access_authentication", "identity_access", (False, False, False, True)),
        ("software_application", "application_support", (False, False, False, True)),
        ("hardware_device", "service_desk", (False, False, False, True)),
        ("network_connectivity", "infrastructure_network", (False, False, False, True)),
        ("security_incident", "security", (True, True, True, True)),
        ("other", "service_desk", (True, True, True, True)),
    ],
)
@pytest.mark.parametrize("priority_index,priority", list(enumerate(TicketPriority)))
def test_triage_routes_and_reviews_all_categories_and_priorities(
    classifier: Mock,
    category: str,
    department: str,
    reviews: tuple[bool, ...],
    priority_index: int,
    priority: TicketPriority,
) -> None:
    ticket = TicketRequest(
        ticket_id="TCK-1001",
        subject="Support request",
        description="Please review this issue.",
    )
    classification = LLMClassificationResult(
        category=category,
        priority=priority,
        summary="The user requests help with an issue.",
        suggested_action="Ask for details about the issue.",
    )
    classifier.return_value = classification
    original_ticket = ticket.model_dump()
    original_classification = classification.model_dump()

    result = service.triage_ticket(ticket)

    classifier.assert_called_once_with(ticket)
    assert isinstance(result, TriageResponse)
    assert result.model_dump(mode="json") == {
        **classification.model_dump(mode="json"),
        "ticket_id": "TCK-1001",
        "department": department,
        "needs_human_review": reviews[priority_index],
    }
    assert ticket.model_dump() == original_ticket
    assert classification.model_dump() == original_classification


@pytest.mark.parametrize("ticket_id", [None, "TCK-1002"])
def test_triage_preserves_optional_ticket_id(
    classifier: Mock, ticket_id: str | None
) -> None:
    ticket = TicketRequest(
        ticket_id=ticket_id,
        subject="Printer",
        description="The printer prints blank pages.",
    )
    classifier.return_value = LLMClassificationResult(
        category="hardware_device",
        priority="medium",
        summary="Printer prints blank pages.",
        suggested_action="Check the ink level.",
    )

    assert service.triage_ticket(ticket).ticket_id == ticket_id
    classifier.assert_called_once_with(ticket)


@pytest.mark.parametrize(
    "error_type",
    [
        llm_client.LLMClientError,
        llm_client.LLMTimeoutError,
        llm_client.LLMResponseError,
        RuntimeError,
    ],
)
def test_client_errors_propagate_without_fallback_or_retry(
    classifier: Mock, error_type: type[Exception]
) -> None:
    ticket = TicketRequest(
        subject="Printer", description="The printer prints blank pages."
    )
    failure = error_type("Provider classification failed.")
    classifier.side_effect = failure

    with pytest.raises(error_type) as error:
        service.triage_ticket(ticket)

    assert error.value is failure
    classifier.assert_called_once_with(ticket)

"""Schema contract tests that run without provider access."""

import json

import pytest
from pydantic import BaseModel, ValidationError

from app.enums import Department, TicketCategory, TicketPriority
from app.schemas import LLMClassificationResult, TicketRequest, TriageResponse

REQUEST = {
    "subject": "VPN connection problem",
    "description": "I cannot connect to the corporate VPN after changing my password.",
}
CLASSIFICATION = {
    "category": "access_authentication",
    "priority": "high",
    "summary": "User cannot connect to the corporate VPN after a password change.",
    "suggested_action": "Verify credential synchronization.",
}
RESPONSE = {
    **CLASSIFICATION,
    "ticket_id": "TCK-1001",
    "department": "identity_access",
    "needs_human_review": False,
}


@pytest.mark.parametrize("ticket_id", [None, "TCK-1001", "x" * 100])
def test_request_accepts_optional_ticket_id(ticket_id: str | None) -> None:
    ticket = TicketRequest(**REQUEST, ticket_id=ticket_id)

    assert ticket.ticket_id == ticket_id
    assert ticket.subject == REQUEST["subject"]
    assert ticket.description == REQUEST["description"]


def test_request_defaults_ticket_id_to_none() -> None:
    assert TicketRequest(**REQUEST).ticket_id is None


@pytest.mark.parametrize(
    "subject,description", [("x", "x" * 10), ("x" * 200, "x" * 5000)]
)
def test_request_accepts_length_boundaries(subject: str, description: str) -> None:
    ticket = TicketRequest(subject=subject, description=description)

    assert ticket.subject == subject
    assert ticket.description == description


def test_request_strips_surrounding_whitespace_before_validation() -> None:
    ticket = TicketRequest(
        ticket_id=" TCK-1001 ", subject=" VPN ", description="  Cannot log in.  "
    )

    assert ticket.model_dump() == {
        "ticket_id": "TCK-1001",
        "subject": "VPN",
        "description": "Cannot log in.",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("subject", ""),
        ("subject", " \t\n "),
        ("subject", "x" * 201),
        ("subject", None),
        ("subject", 123),
        ("description", "x" * 9),
        ("description", " " * 10),
        ("description", "  short  "),
        ("description", "x" * 5001),
        ("description", None),
        ("description", 123),
        ("ticket_id", "x" * 101),
        ("ticket_id", 123),
    ],
)
def test_request_rejects_invalid_fields(field: str, value: object) -> None:
    with pytest.raises(ValidationError) as error:
        TicketRequest.model_validate({**REQUEST, field: value})

    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize(
    "model,payload,field",
    [
        (TicketRequest, REQUEST, "subject"),
        (TicketRequest, REQUEST, "description"),
        *[
            (LLMClassificationResult, CLASSIFICATION, field)
            for field in ("category", "priority", "summary", "suggested_action")
        ],
        *[
            (TriageResponse, RESPONSE, field)
            for field in (
                "ticket_id",
                "category",
                "department",
                "priority",
                "summary",
                "suggested_action",
                "needs_human_review",
            )
        ],
    ],
)
def test_required_fields(
    model: type[BaseModel], payload: dict[str, object], field: str
) -> None:
    incomplete = {key: value for key, value in payload.items() if key != field}

    with pytest.raises(ValidationError) as error:
        model.model_validate(incomplete)

    assert error.value.errors()[0]["loc"] == (field,)
    assert error.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize(
    "enum,values",
    [
        (
            TicketCategory,
            {
                "access_authentication",
                "software_application",
                "hardware_device",
                "network_connectivity",
                "security_incident",
                "other",
            },
        ),
        (TicketPriority, {"low", "medium", "high", "critical"}),
        (
            Department,
            {
                "identity_access",
                "application_support",
                "service_desk",
                "infrastructure_network",
                "security",
            },
        ),
    ],
)
def test_enum_taxonomy(enum: type, values: set[str]) -> None:
    assert {member.value for member in enum} == values


@pytest.mark.parametrize("category", list(TicketCategory))
def test_classification_accepts_categories(category: TicketCategory) -> None:
    result = LLMClassificationResult.model_validate(
        {**CLASSIFICATION, "category": category.value}
    )
    assert result.category is category


@pytest.mark.parametrize("priority", list(TicketPriority))
def test_classification_accepts_priorities(priority: TicketPriority) -> None:
    result = LLMClassificationResult.model_validate(
        {**CLASSIFICATION, "priority": priority.value}
    )
    assert result.priority is priority


@pytest.mark.parametrize("department", list(Department))
def test_response_accepts_departments(department: Department) -> None:
    result = TriageResponse.model_validate({**RESPONSE, "department": department.value})
    assert result.department is department


@pytest.mark.parametrize(
    "model,payload",
    [(LLMClassificationResult, CLASSIFICATION), (TriageResponse, RESPONSE)],
)
@pytest.mark.parametrize(
    "field,value",
    [
        ("category", "billing"),
        ("category", "ACCESS_AUTHENTICATION"),
        ("priority", "urgent"),
        ("priority", None),
        ("summary", ""),
        ("summary", " \n "),
        ("summary", 123),
        ("suggested_action", ""),
        ("suggested_action", " \t "),
        ("suggested_action", None),
    ],
)
def test_result_rejects_invalid_fields(
    model: type[BaseModel], payload: dict[str, object], field: str, value: object
) -> None:
    with pytest.raises(ValidationError) as error:
        model.model_validate({**payload, field: value})

    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize(
    "field,value",
    [("department", "finance"), ("needs_human_review", None), ("ticket_id", "x" * 101)],
)
def test_response_rejects_invalid_additional_fields(field: str, value: object) -> None:
    with pytest.raises(ValidationError) as error:
        TriageResponse.model_validate({**RESPONSE, field: value})

    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize(
    "model,payload,extra",
    [
        (TicketRequest, REQUEST, {"priority": "critical"}),
        (LLMClassificationResult, CLASSIFICATION, {"department": "security"}),
        (LLMClassificationResult, CLASSIFICATION, {"needs_human_review": True}),
        (TriageResponse, RESPONSE, {"unexpected": "value"}),
    ],
)
def test_models_reject_unexpected_fields(
    model: type[BaseModel], payload: dict[str, object], extra: dict[str, object]
) -> None:
    with pytest.raises(ValidationError) as error:
        model.model_validate({**payload, **extra})

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_classification_serializes_only_classification_fields() -> None:
    result = LLMClassificationResult.model_validate(CLASSIFICATION)

    assert json.loads(result.model_dump_json()) == CLASSIFICATION


@pytest.mark.parametrize("ticket_id", ["TCK-1001", None])
def test_response_json_round_trip(ticket_id: str | None) -> None:
    payload = {**RESPONSE, "ticket_id": ticket_id}
    result = TriageResponse.model_validate(payload)

    assert result.category is TicketCategory.ACCESS_AUTHENTICATION
    assert result.priority is TicketPriority.HIGH
    assert result.department is Department.IDENTITY_ACCESS
    assert result.needs_human_review is False
    assert json.loads(result.model_dump_json()) == payload
    assert TriageResponse.model_validate_json(result.model_dump_json()) == result

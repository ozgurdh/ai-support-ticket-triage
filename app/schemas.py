"""Validated API contracts and provider-independent classification output."""

from pydantic import BaseModel, ConfigDict, Field

from app.enums import Department, TicketCategory, TicketPriority


class TicketRequest(BaseModel):
    """A support ticket submitted for classification."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    ticket_id: str | None = Field(default=None, max_length=100)
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=10, max_length=5000)


class LLMClassificationResult(BaseModel):
    """Only the fields that require natural-language classification."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    category: TicketCategory
    priority: TicketPriority
    summary: str = Field(min_length=1)
    suggested_action: str = Field(min_length=1)


class TriageResponse(BaseModel):
    """Final triage data; business-rule fields are supplied by the service."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    ticket_id: str | None = Field(max_length=100)
    category: TicketCategory
    department: Department
    priority: TicketPriority
    summary: str = Field(min_length=1)
    suggested_action: str = Field(min_length=1)
    needs_human_review: bool

"""Basic FastAPI endpoints with a temporary mock triage response."""

from fastapi import FastAPI

from app.enums import Department, TicketCategory, TicketPriority
from app.schemas import TicketRequest, TriageResponse

app = FastAPI(
    title="AI Support Ticket Triage API",
    description="Ticket validation with a temporary deterministic mock triage result.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/triage", response_model=TriageResponse)
def triage(ticket: TicketRequest) -> TriageResponse:
    """Validate a ticket and return mock values without classifying its content."""
    return TriageResponse(
        ticket_id=ticket.ticket_id,
        category=TicketCategory.OTHER,
        department=Department.SERVICE_DESK,
        priority=TicketPriority.MEDIUM,
        summary="Mock triage result; ticket has not been classified.",
        suggested_action="Review the ticket manually.",
        needs_human_review=True,
    )

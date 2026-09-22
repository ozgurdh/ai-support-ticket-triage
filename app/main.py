"""FastAPI endpoints for support-ticket triage."""

from fastapi import FastAPI

from app import service
from app.schemas import TicketRequest, TriageResponse

app = FastAPI(
    title="AI Support Ticket Triage API",
    description="Ticket classification with deterministic routing and human review.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/triage", response_model=TriageResponse)
def triage(ticket: TicketRequest) -> TriageResponse:
    """Return the service's triage result for a validated ticket."""
    return service.triage_ticket(ticket)

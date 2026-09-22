"""Deterministic routing and human-review rules for classified support tickets."""

from app import llm_client
from app.enums import Department, TicketCategory, TicketPriority
from app.schemas import TicketRequest, TriageResponse

CATEGORY_TO_DEPARTMENT: dict[TicketCategory, Department] = {
    TicketCategory.ACCESS_AUTHENTICATION: Department.IDENTITY_ACCESS,
    TicketCategory.SOFTWARE_APPLICATION: Department.APPLICATION_SUPPORT,
    TicketCategory.HARDWARE_DEVICE: Department.SERVICE_DESK,
    TicketCategory.NETWORK_CONNECTIVITY: Department.INFRASTRUCTURE_NETWORK,
    TicketCategory.SECURITY_INCIDENT: Department.SECURITY,
    TicketCategory.OTHER: Department.SERVICE_DESK,
}


def triage_ticket(ticket: TicketRequest) -> TriageResponse:
    """Classify once and derive application-owned fields from the validated result."""
    classification = llm_client.classify_ticket(ticket)
    needs_human_review = (
        classification.category
        in (TicketCategory.SECURITY_INCIDENT, TicketCategory.OTHER)
        or classification.priority == TicketPriority.CRITICAL
    )
    return TriageResponse(
        ticket_id=ticket.ticket_id,
        category=classification.category,
        department=CATEGORY_TO_DEPARTMENT[classification.category],
        priority=classification.priority,
        summary=classification.summary,
        suggested_action=classification.suggested_action,
        needs_human_review=needs_human_review,
    )

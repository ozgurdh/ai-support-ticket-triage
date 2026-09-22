"""FastAPI endpoints for support-ticket triage."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import service
from app.llm_client import LLMClientError, LLMTimeoutError
from app.schemas import TicketRequest, TriageResponse

app = FastAPI(
    title="AI Support Ticket Triage API",
    description="Ticket classification with deterministic routing and human review.",
)


@app.exception_handler(LLMClientError)
async def provider_error_handler(
    request: Request, error: LLMClientError
) -> JSONResponse:
    if isinstance(error, LLMTimeoutError):
        return JSONResponse(
            status_code=504, content={"detail": "Provider request timed out."}
        )
    return JSONResponse(status_code=503, content={"detail": "Provider unavailable."})


@app.exception_handler(Exception)
async def server_error_handler(request: Request, error: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/v1/triage",
    response_model=TriageResponse,
    responses={
        500: {"description": "Unexpected server or configuration error"},
        503: {"description": "Provider unavailable or no valid classification"},
        504: {"description": "Provider timeout"},
    },
)
def triage(ticket: TicketRequest) -> TriageResponse:
    """Return the service's triage result for a validated ticket."""
    return service.triage_ticket(ticket)

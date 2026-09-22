"""Request metadata only: never serialize bodies, headers, or exception messages."""

import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.requests")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


@dataclass
class RequestLogContext:
    request_id: str
    model: str | None = None
    error_type: str | None = None


# A separate object per request is shared with FastAPI's sync worker thread.
# Mutating its metadata makes the model visible to the outer middleware.
_context: ContextVar[RequestLogContext | None] = ContextVar("request_log", default=None)


def record_model(model: str) -> None:
    """Record the actual configured model without passing HTTP objects to the client."""
    context = _context.get()
    if context is not None:
        context.model = model


def record_error(request: Request, error: Exception) -> None:
    request.state.log_context.error_type = type(error).__name__


async def log_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
    supplied_id = request.headers.get("X-Request-ID", "")
    request_id = (
        supplied_id
        if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied_id)
        else str(uuid4())
    )
    context = RequestLogContext(request_id=request_id)
    request.state.log_context = context
    token = _context.set(context)
    started = perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as error:
        record_error(request, error)
        raise
    finally:
        _context.reset(token)
        # Route templates exclude query strings and user-supplied path values.
        route = request.scope.get("route")
        metadata = {
            "request_id": request_id,
            "endpoint": getattr(route, "path", "<unmatched>"),
            "status_code": status_code,
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "model": context.model,
            "error_type": context.error_type
            or ("HTTPError" if status_code >= 400 else None),
        }
        level = logging.ERROR if status_code >= 500 else logging.INFO
        logger.log(level, json.dumps(metadata))

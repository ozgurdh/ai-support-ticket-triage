"""OpenAI structured classification with a single provider attempt per call."""

from typing import cast

from openai import APIError, APIResponseValidationError, APITimeoutError, OpenAI
from openai.types.responses import ResponseInputParam
from pydantic import ValidationError

from app.config import Settings
from app.prompt import build_messages
from app.schemas import LLMClassificationResult, TicketRequest


class LLMClientError(Exception):
    """The provider could not complete the classification request."""


class LLMTimeoutError(LLMClientError):
    """The provider request timed out."""


class LLMResponseError(LLMClientError):
    """The provider did not return a complete, valid classification."""


def classify_ticket(
    ticket: TicketRequest, settings: Settings | None = None
) -> LLMClassificationResult:
    """Classify a validated ticket; configuration errors remain local errors."""
    if settings is None:
        settings = Settings()
    messages = build_messages(ticket)

    try:
        with OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
            max_retries=0,
        ) as client:
            response = client.responses.parse(
                model=settings.openai_model,
                input=cast(ResponseInputParam, messages),
                text_format=LLMClassificationResult,
                store=False,
            )

        if response.status != "completed" or response.output_parsed is None:
            raise LLMResponseError("Provider did not return a complete classification.")
        return LLMClassificationResult.model_validate(response.output_parsed)
    except APITimeoutError:
        raise LLMTimeoutError("Provider request timed out.") from None
    except (ValidationError, APIResponseValidationError):
        raise LLMResponseError("Provider returned an invalid classification.") from None
    except APIError:
        raise LLMClientError("Provider request failed.") from None

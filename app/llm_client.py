"""OpenAI structured classification with bounded retries for transient failures."""

from time import sleep
from typing import cast

from openai import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)
from openai.types.responses import ResponseInputParam
from pydantic import ValidationError
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_fixed

from app.config import Settings
from app.prompt import build_messages
from app.schemas import LLMClassificationResult, TicketRequest


class LLMClientError(Exception):
    """The provider could not complete the classification request."""


class LLMTimeoutError(LLMClientError):
    """The provider request timed out."""


class LLMResponseError(LLMClientError):
    """The provider did not return a complete, valid classification."""


class _RecoverableResponseError(LLMResponseError):
    """A fresh generation may recover from malformed or missing model output."""


def _is_retryable(error: BaseException) -> bool:
    if isinstance(
        error,
        (APIConnectionError, APIResponseValidationError, _RecoverableResponseError),
    ):
        return True
    if not isinstance(error, APIStatusError):
        return False
    if error.status_code not in (408, 409, 429, 500, 502, 503, 504):
        return False
    quota_codes = {
        "insufficient_quota",
        "credit_balance_exhausted",
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
        "organization_usage_limit_exceeded",
    }
    if error.code in quota_codes or error.type == "insufficient_quota":
        return False
    # Leave server-directed delays to the caller instead of retrying too early
    # or keeping this synchronous request waiting for an unbounded interval.
    headers = error.response.headers
    return not (
        headers.get("x-should-retry") == "false"
        or "retry-after" in headers
        or "retry-after-ms" in headers
    )


def _request_classification(
    client: OpenAI, model: str, messages: ResponseInputParam
) -> LLMClassificationResult:
    try:
        response = client.responses.parse(
            model=model,
            input=messages,
            text_format=LLMClassificationResult,
            store=False,
        )
    except ValidationError as error:
        # Only validation of the SDK's generated classification is recoverable.
        # Request/configuration validation is outside this provider operation.
        if error.title != LLMClassificationResult.__name__:
            raise
        raise _RecoverableResponseError(
            "Provider returned an invalid classification."
        ) from None

    if any(
        content.type == "refusal"
        for output in response.output
        if output.type == "message"
        for content in output.content
    ):
        raise LLMResponseError("Provider declined to classify the ticket.")
    if response.status != "completed":
        # Repeating the same request cannot fix a token limit or content filter.
        raise LLMResponseError("Provider did not return a complete classification.")
    if response.output_parsed is None:
        raise _RecoverableResponseError("Provider returned no classification.")
    return response.output_parsed


def classify_ticket(
    ticket: TicketRequest, settings: Settings | None = None
) -> LLMClassificationResult:
    """Classify a validated ticket; configuration errors remain local errors."""
    if settings is None:
        settings = Settings()
    messages = cast(ResponseInputParam, build_messages(ticket))

    try:
        with OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
            max_retries=0,
        ) as client:
            retrying = Retrying(
                stop=stop_after_attempt(2),
                wait=wait_fixed(0.5),
                retry=retry_if_exception(_is_retryable),
                sleep=sleep,
                reraise=True,
            )
            classification = retrying(
                _request_classification, client, settings.openai_model, messages
            )

        # Keep local validation outside the retry operation.
        return LLMClassificationResult.model_validate(classification)
    except APITimeoutError:
        raise LLMTimeoutError("Provider request timed out.") from None
    except APIResponseValidationError:
        raise LLMResponseError("Provider returned an invalid classification.") from None
    except APIStatusError as error:
        if error.status_code in (408, 504):
            raise LLMTimeoutError("Provider request timed out.") from None
        raise LLMClientError("Provider request failed.") from None
    except APIError:
        raise LLMClientError("Provider request failed.") from None

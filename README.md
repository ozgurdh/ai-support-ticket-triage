# AI Support Ticket Triage API

A FastAPI service for converting unstructured IT support tickets into
validated triage results using an LLM and deterministic business rules.

## Current status

TASK-001 initializes the repository: Python packaging, dependencies, development
tools, an importable `app` package, and an environment-variable template.
TASK-002 adds domain enums and validated request, classification, and response
schemas with automated tests. TASK-003 adds the health and triage endpoints with
a deterministic mock response and Swagger documentation. TASK-004 adds the prompt
builder, taxonomy descriptions, priority rubric, and input trust instructions.
TASK-005 adds a standalone OpenAI client with structured classification, validated
environment settings, and timeout/error foundations. TASK-006 connects the API to
the LLM client through a service that derives department routing and human review.
TASK-007 adds bounded retries for transient provider failures and safe HTTP error
responses. TASK-008 adds request logging and correlation IDs. TASK-009 completes
the automated behavioral test suite, including provider and logging failure paths.
TASK-010 adds the labelled evaluation dataset. TASK-011 adds an explicitly invoked
evaluation runner and offline tests of its scoring. Model evaluation and prompt
refinement and CI are scheduled for later tasks. TASK-013 adds a Docker image.

See [the project plan](docs/PROJECT_PLAN.md) for the specification and roadmap,
and [AGENTS.md](AGENTS.md) for development guidelines.

## Foundation stack

- Python 3.11+
- FastAPI, Uvicorn, Pydantic, and pydantic-settings
- OpenAI Python SDK and Tenacity
- pytest, httpx, and Ruff for development

Dependencies are declared in `pyproject.toml`. `requirements.txt` installs the
project in editable mode with its development tools.

## Setup

Run these commands from the repository root.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -c "import app; print('Project imports successfully')"
```

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c "import app; print('Project imports successfully')"
```

## Running locally

Configure `.env` as described below to classify tickets, then start the application
from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

On macOS / Linux, use `.venv/bin/python -m uvicorn app.main:app --reload`.
Open [Swagger UI](http://localhost:8000/docs) to try the endpoints. The OpenAPI
schema is available at [openapi.json](http://localhost:8000/openapi.json).

## Docker

Build and run the API from the repository root:

```powershell
docker build -t ticket-triage-api .
docker run --rm -p 8000:8000 --env-file .env ticket-triage-api
```

The container listens on port 8000. Open `http://localhost:8000/health` to
check it. The `.env` file is supplied only when the container starts; it is
excluded from the image. Omit `--env-file .env` when checking `/health` without
provider credentials. Triage requests require the configured key and model.

## API usage

`GET /health` returns HTTP 200 with `{"status": "ok"}` without calling the provider.

`POST /api/v1/triage` validates a JSON ticket, calls the configured LLM, and applies
deterministic routing and review rules. It returns HTTP 200 on success. This now
makes a real provider request and requires `OPENAI_API_KEY` and `OPENAI_MODEL`.
For example, submit this body through Swagger UI:

```json
{
  "ticket_id": "TCK-1001",
  "subject": "VPN connection problem",
  "description": "I cannot connect to the corporate VPN after changing my password."
}
```

Illustrative response (model-generated values may vary):

```json
{
  "ticket_id": "TCK-1001",
  "category": "access_authentication",
  "department": "identity_access",
  "priority": "high",
  "summary": "User cannot connect to the VPN after a password change.",
  "suggested_action": "Verify credential synchronization.",
  "needs_human_review": false
}
```

The response preserves the validated `ticket_id`, which is `null` when omitted.
Invalid requests return HTTP 422 before calling the LLM client. The endpoint uses
`TicketRequest` and `TriageResponse` for request and response validation.
Failures return the following HTTP responses after any eligible retry:

| Failure | Status | Response detail |
| --- | --- | --- |
| Invalid request | 422 | Request validation errors |
| Provider unavailable or invalid classification | 503 | `Provider unavailable.` |
| Provider timeout | 504 | `Provider request timed out.` |
| Configuration or unexpected server error | 500 | `Internal server error.` |

Provider and server error responses do not expose exception details or model output.

## Request logging

Every response includes `X-Request-ID`, including validation and server errors.
Clients may supply this header to correlate requests: accepted IDs contain 1–64
ASCII letters, digits, dots, underscores, or hyphens. Missing or invalid IDs are
replaced with a generated UUID. IDs should contain only correlation identifiers.

The `app.requests` logger writes one JSON record to stderr for each HTTP request,
using Python's standard logging module. It includes `request_id`, `endpoint`,
`status_code`, `latency_ms`, `model`, and `error_type`. Successful and client-error
requests use INFO; server/provider errors use ERROR. Latency uses a monotonic
clock and measures processing until the response is ready, including retries.
The model is recorded from the LLM client's validated settings; it is `null` for
requests that never reach that point, such as health checks or invalid input.
Error types are exception class names; successful requests have `null`.

Request logs exclude ticket IDs, subjects, descriptions, generated classifications,
authorization headers, API keys, and exception messages/tracebacks. Endpoint
values use route templates without query strings; unmatched paths are recorded
as `<unmatched>`. Logging metadata is isolated per request, including concurrent
requests handled by synchronous workers. These records are separate from the
web server's own access/error logs and any explicitly enabled dependency debug logs.

## Environment variables

`app/config.py` loads the following variables from the environment or a local
`.env` file. Environment variables take precedence over `.env` values.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required, nonblank provider API key; blank in the template. |
| `OPENAI_MODEL` | Required model supporting Responses API structured outputs; blank in the template. |
| `OPENAI_TIMEOUT_SECONDS` | Positive, finite SDK timeout in seconds; defaults to 30. |

To use the LLM client, copy `.env.example` to `.env` and set the key and model.
Settings are loaded when the client is called, so imports, health, API docs,
and tests do not require credentials. API keys use Pydantic `SecretStr` to mask
their normal representation. `.env` and local virtual environments are ignored
by Git; never commit credentials.

## Development checks

Using the virtual environment's Python (Windows commands shown):

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest
```

On macOS / Linux, use `.venv/bin/python` instead.

Schema tests cover field requirements, length boundaries, enum values, invalid
input, and JSON serialization. Service tests cover all category/priority combinations,
field preservation, and propagation of client errors. Service and API tests mock
the LLM client. API tests exercise routing, human review, request and response
validation, safe error responses, health, Swagger, and OpenAPI. Prompt tests cover taxonomy
and rubric coverage, output instructions, ticket formatting, and separation of
ticket content from system instructions. Tests run without API keys or real LLM
calls; they do not measure model accuracy or resistance to prompt injection.
Settings tests isolate environment and dotenv values. LLM client tests exercise
the SDK against an in-memory HTTP mock, including structured-output validation,
timeouts, provider errors, refusals, and incomplete responses. Retry tests cover
recovery, the two-attempt limit, non-retryable failures, and propagation to HTTP
responses. Retry delays are mocked so tests do not sleep.
Logging tests cover correlation IDs, latency, safe error metadata, sensitive-data
exclusion, and isolation between concurrent requests. SDK tests verify that the
actual configured model appears in request logs without exposing API keys.

The suite also exercises the complete API-to-mocked-provider path: recovery after
a retry, exhausted timeouts (504), exhausted rate limits and provider failures
(503), authentication failures without retry, and invalid configuration without
provider access. Mixed failures verify that the last attempt determines the HTTP
error. Logging tests cover concurrent success/failure requests and invalid service
responses without exposing their contents.

`tests/conftest.py` blocks the real synchronous and asynchronous HTTPX transports.
An omitted provider mock therefore fails the test before an outbound HTTP request
can be sent. FastAPI's in-process test transport and SDK `MockTransport` remain
available. Tests use dummy credentials and require no real OpenAI access.

## Domain models and validation

`app/enums.py` defines the planned category, priority, and department values.
`app/schemas.py` provides three separate Pydantic models:

- `TicketRequest`: optional `ticket_id` (up to 100 characters, default `None`),
  required `subject` (1–200 characters), and `description` (10–5000 characters).
- `LLMClassificationResult`: required `category`, `priority`, `summary`, and
  `suggested_action`. It contains only classification fields.
- `TriageResponse`: classification fields plus a required, nullable `ticket_id`
  (up to 100 characters), `department`, and `needs_human_review`.

Surrounding whitespace is stripped from text fields before length validation.
Summary and suggested action must contain at least one non-whitespace character.
Unknown fields and invalid enum values are rejected. Schemas validate supplied
fields; the service derives department routing and human-review decisions.

## Triage service

`app.service.triage_ticket(ticket)` calls the existing LLM client once, preserves
its category, priority, summary, and suggested action, and builds a `TriageResponse`.
The service derives the department using this mapping:

| Category | Department |
| --- | --- |
| `access_authentication` | `identity_access` |
| `software_application` | `application_support` |
| `hardware_device` | `service_desk` |
| `network_connectivity` | `infrastructure_network` |
| `security_incident` | `security` |
| `other` | `service_desk` |

`needs_human_review` is true when the category is `security_incident` or `other`,
or the priority is `critical`. It is false otherwise. Both rules live in the
service and are independent of model-generated text. The service propagates
client errors without retrying or returning a fallback classification.

## Prompt builder

`app/prompt.py` contains `SYSTEM_PROMPT`, `format_ticket(ticket)`, and
`build_messages(ticket)`. The builder returns separate system and user messages.
The user message contains JSON-encoded subject and description; the ticket ID is
excluded because it is not needed for classification.

The system prompt describes all category and priority enum values using the
project plan's definitions. It requests only the four classification fields,
requires factual summaries and a safe initial action, and instructs the model to
treat ticket text as untrusted data and ignore embedded instructions.

The LLM client uses this builder when called by the triage service.

## LLM client

`app.llm_client.classify_ticket(ticket, settings=None)` accepts a validated
`TicketRequest` and returns `LLMClassificationResult`. It uses the OpenAI
Responses API's `responses.parse` method with the existing Pydantic schema,
following the [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).
The SDK dependency now requires version 2.54 or later within major version 2,
the baseline tested for this integration.

The following explicitly invokes the real provider after configuring `.env`:

```python
from app.llm_client import classify_ticket
from app.schemas import TicketRequest

ticket = TicketRequest(
    subject="VPN connection problem",
    description="I cannot connect to the corporate VPN after changing my password.",
)
result = classify_ticket(ticket)
```

An optional `Settings` instance can supply configuration explicitly. The client
requests `store=False` and closes its SDK connection after each call. Tenacity
allows at most two attempts with a fixed 0.5-second delay. SDK retries remain
disabled so they cannot multiply the attempt count. The configured timeout
applies to SDK network operations on each attempt; it is not an overall
application deadline.

Connection failures, timeouts, HTTP 408/409/429 and temporary server errors
(500/502/503/504), and malformed or missing structured output may retry.
Credentials, invalid requests, quota/billing failures, configuration errors,
and local schema validation do not retry. Refusals and incomplete responses
reported by the SDK also fail without retry. When the provider sends a
`Retry-After`/`retry-after-ms` header or explicitly forbids retry, the client
returns the failure immediately rather than retrying ahead of the provider's
delay or waiting for an unbounded interval.

`LLMTimeoutError` identifies timeouts, `LLMResponseError` identifies invalid,
missing, refused, or incomplete classifications, and `LLMClientError` handles
other provider failures. These errors use generic messages without provider
payloads. Missing or invalid settings raise local Pydantic validation errors
before any provider request. Provider error handling and retry policy stay in
`llm_client.py`; HTTP error mapping stays in `main.py`. Routing and human-review
decisions remain in the service.

## Evaluation dataset

[`evaluation/eval_tickets.jsonl`](evaluation/eval_tickets.jsonl) contains 50
synthetic support tickets with individually assigned reference labels and a
per-ticket rationale checked against the existing taxonomy and priority rubric.
These examples are authored fixtures, not real customer tickets or model predictions.

Each UTF-8 JSONL row contains `subject`, `description`, `expected_category`, and
`expected_priority`, plus a unique `id`, `scenario_types` (a list of tags), and
`notes` explaining the labels. Only subject and description are classification
input; expected labels, tags, and notes are reference metadata.

| Category | Low | Medium | High | Critical | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| `access_authentication` | 2 | 2 | 4 | 1 | 9 |
| `software_application` | 3 | 3 | 2 | 1 | 9 |
| `hardware_device` | 2 | 3 | 2 | 1 | 8 |
| `network_connectivity` | 2 | 2 | 2 | 2 | 8 |
| `security_incident` | 1 | 1 | 2 | 4 | 8 |
| `other` | 4 | 2 | 1 | 1 | 8 |
| **Total** | **14** | **13** | **13** | **10** | **50** |

Overlapping edge-case tags identify 7 ambiguous cases, 5 multi-issue tickets,
5 short tickets, 6 prompt-injection attempts, 10 critical incidents, 6 company-wide
incidents, and 2 irrelevant requests. Short descriptions still meet the API's
10-character minimum. Injection cases include subject role claims, embedded JSON,
code blocks, XML delimiters, severity inflation, and attempted severity suppression.

Multi-issue labels follow the explicitly stated primary issue. Ambiguous examples
retain uncertainty instead of guessing a root cause; stated impact determines
priority. The detail-free help request is labelled low with a clarification rationale.
Security examples span all priorities so security classification alone does not
imply critical impact. Category counts are nearly balanced; critical cases are
deliberately included across categories. This is a coverage-oriented starter set,
not an estimate of real support traffic or independently human-adjudicated ground truth.

All rows were validated as JSON, checked against `TicketRequest` and the category
and priority enums, and checked for duplicate IDs and ticket texts. No provider
calls or model evaluation have been run for this dataset, so no accuracy or other
evaluation metrics are reported.

## Running evaluation

From the repository root, after configuring `.env`, explicitly run:

```powershell
.\.venv\Scripts\python.exe -m evaluation.evaluate
```

This sends the dataset's tickets through `app.service.triage_ticket`, including
the real LLM client, its timeout/retry policy, and deterministic business rules.
Requests run sequentially and consume provider usage. No API server is needed.
The default dataset is resolved relative to the evaluation module; use
`--dataset path/to/tickets.jsonl` to select another labelled dataset.
Use `--limit N` to evaluate only the first N tickets (N must be positive).

To validate the dataset without credentials or provider access:

```powershell
.\.venv\Scripts\python.exe -m evaluation.evaluate --validate-only
```

On macOS/Linux, replace the executable with `.venv/bin/python`. `--help` lists
the options. Importing the module and running normal `pytest` do not invoke a
live evaluation. Tests of the runner mock the LLM client or service and verify
scoring against hand-calculated fixtures; they are not model performance results.

The entire dataset is checked before provider calls. Invalid rows report their
line number; empty or unreadable datasets and invalid settings stop the run.
Reference labels, IDs, notes, and tags are excluded from classification input.
During evaluation, provider, schema, and unexpected per-ticket failures are
recorded without stopping subsequent tickets. The report lists failed ticket
numbers and exception types. Provider failures also show safe SDK type, HTTP
status, recognized error code/type, and a fixed explanation. Raw ticket text,
provider response messages, and secrets are excluded.

Metric definitions:

- Category and priority accuracy divide correct predictions by all attempted
  tickets, including failures.
- Priority macro F1 averages F1 across all four priority enums. Missing predictions
  count as false negatives. A class with no actual or predicted examples has F1 0.
- Critical recall divides correctly predicted critical tickets by all labelled
  critical tickets, including failed ones. It is `N/A` if none are labelled critical.
- Schema success rate is valid final `TriageResponse` results divided by attempted
  tickets, after any client retry. Provider failures also reduce this rate; it is
  not a measurement of individual generation attempts.
- Average, p50, and p95 latency include successful and failed service calls,
  validation, retries, and retry delays, measured with a monotonic clock in seconds.
  Percentiles use linear interpolation at `(n - 1) * percentile` in sorted samples.

The command prints a summary and exits with 0 when every ticket returns a valid
response, 1 when any ticket fails, or 2 for dataset/configuration errors.
Misclassifications affect scores but are not execution failures. Validation-only
mode exits with 0 for valid data and prints no model metrics.

## Repository structure

```text
app/
    __init__.py
    config.py
    enums.py
    llm_client.py
    main.py
    prompt.py
    request_logging.py
    schemas.py
    service.py
tests/
    .gitkeep
    conftest.py
    test_api.py
    test_config.py
    test_evaluation.py
    test_llm_client.py
    test_prompt.py
    test_request_logging.py
    test_schemas.py
    test_service.py
evaluation/
    eval_tickets.jsonl
    evaluate.py
docs/
    PROJECT_PLAN.md
AGENTS.md
README.md
pyproject.toml
requirements.txt
.env.example
.gitignore
```

## Planned documentation

API usage, architecture, taxonomy, routing and human-review rules, structured
outputs, reliability, evaluation results, and CI will be documented
as their corresponding tasks are implemented.

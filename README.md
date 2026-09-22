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
Retries, provider-specific HTTP error mapping, evaluation, Docker, and CI are
scheduled for later tasks.

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
Provider and configuration errors currently produce the default HTTP 500 response;
retry policies and specific provider HTTP error mapping belong to TASK-007.

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
validation, health, Swagger, and OpenAPI. Prompt tests cover taxonomy
and rubric coverage, output instructions, ticket formatting, and separation of
ticket content from system instructions. Tests run without API keys or real LLM
calls; they do not measure model accuracy or resistance to prompt injection.
Settings tests isolate environment and dotenv values. LLM client tests exercise
the SDK against an in-memory HTTP mock, including structured-output validation,
timeouts, provider errors, refusals, and incomplete responses.

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
requests `store=False` and closes its SDK connection after each call. Each call
makes one attempt, with SDK retries disabled. The configured timeout applies to
SDK network operations; it is not an overall application deadline.

`LLMTimeoutError` identifies timeouts, `LLMResponseError` identifies invalid,
missing, refused, or incomplete classifications, and `LLMClientError` handles
other provider failures. These errors use generic messages without provider
payloads. Missing or invalid settings raise local Pydantic validation errors
before any provider request. Routing, human-review decisions, HTTP error mapping,
and retry policies are not implemented in this client.

## Repository structure

```text
app/
    __init__.py
    config.py
    enums.py
    llm_client.py
    main.py
    prompt.py
    schemas.py
    service.py
tests/
    .gitkeep
    test_api.py
    test_config.py
    test_llm_client.py
    test_prompt.py
    test_schemas.py
    test_service.py
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
outputs, reliability, evaluation results, Docker usage, and CI will be documented
as their corresponding tasks are implemented.

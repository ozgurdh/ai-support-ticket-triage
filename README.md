# AI Support Ticket Triage API

A planned FastAPI service for converting unstructured IT support tickets into
validated triage results using an LLM and deterministic business rules.

## Current status

TASK-001 initializes the repository: Python packaging, dependencies, development
tools, an importable `app` package, and an environment-variable template.
TASK-002 adds domain enums and validated request, classification, and response
schemas with automated tests. TASK-003 adds the health and triage endpoints with
a deterministic mock response and Swagger documentation. TASK-004 adds the prompt
builder, taxonomy descriptions, priority rubric, and input trust instructions.
LLM integration, business rules, evaluation, Docker, and CI are scheduled for
later tasks.

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

Start the application from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

On macOS / Linux, use `.venv/bin/python -m uvicorn app.main:app --reload`.
Open [Swagger UI](http://localhost:8000/docs) to try the endpoints. The OpenAPI
schema is available at [openapi.json](http://localhost:8000/openapi.json).

## API usage (temporary mock)

`GET /health` returns HTTP 200 with `{"status": "ok"}`.

`POST /api/v1/triage` accepts a JSON ticket and returns HTTP 200 after validation.
For example, submit this body through Swagger UI:

```json
{
  "ticket_id": "TCK-1001",
  "subject": "VPN connection problem",
  "description": "I cannot connect to the corporate VPN after changing my password."
}
```

Response:

```json
{
  "ticket_id": "TCK-1001",
  "category": "other",
  "department": "service_desk",
  "priority": "medium",
  "summary": "Mock triage result; ticket has not been classified.",
  "suggested_action": "Review the ticket manually.",
  "needs_human_review": true
}
```

Every valid ticket receives the same mock values except for its validated
`ticket_id`, which is `null` when omitted. Ticket content is not classified yet.
Invalid requests return HTTP 422. The endpoint uses `TicketRequest` and
`TriageResponse` for request and response validation. No API key is required.

## Environment variables

`.env.example` contains placeholders for the planned provider configuration:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Provider API key; blank in the template. |
| `OPENAI_MODEL` | Model name; blank in the template. |
| `OPENAI_TIMEOUT_SECONDS` | Planned provider timeout; template value is 30 seconds. |

No API key is needed for repository setup or import checks. Environment loading
and provider calls are not implemented yet. When integration is added, copy
`.env.example` to `.env` and set local values. `.env` and local virtual
environments are ignored by Git; never commit credentials.

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
input, and JSON serialization. API tests cover health, mock triage responses,
request and response validation, Swagger, and OpenAPI. Prompt tests cover taxonomy
and rubric coverage, output instructions, ticket formatting, and separation of
ticket content from system instructions. Tests run without API keys or real LLM
calls; they do not measure model accuracy or resistance to prompt injection.

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
Unknown fields and invalid enum values are rejected. Department routing and
human-review decisions will be implemented in the service task; these schemas
only validate the supplied fields.

## Prompt builder

`app/prompt.py` contains `SYSTEM_PROMPT`, `format_ticket(ticket)`, and
`build_messages(ticket)`. The builder returns separate system and user messages.
The user message contains JSON-encoded subject and description; the ticket ID is
excluded because it is not needed for classification.

The system prompt describes all category and priority enum values using the
project plan's definitions. It requests only the four classification fields,
requires factual summaries and a safe initial action, and instructs the model to
treat ticket text as untrusted data and ignore embedded instructions.

The prompt builder is not connected to the API yet. The triage endpoint continues
to return its temporary mock response. Provider calls and structured-output
integration belong to TASK-005.

## Repository structure

```text
app/
    __init__.py
    enums.py
    main.py
    prompt.py
    schemas.py
tests/
    .gitkeep
    test_api.py
    test_prompt.py
    test_schemas.py
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

# AI Support Ticket Triage API

A planned FastAPI service for converting unstructured IT support tickets into
validated triage results using an LLM and deterministic business rules.

## Current status

TASK-001 initializes the repository: Python packaging, dependencies, development
tools, an importable `app` package, and an environment-variable template.
TASK-002 adds domain enums and validated request, classification, and response
schemas with automated tests. API endpoints, LLM integration, evaluation, Docker,
and CI are scheduled for later tasks and are not implemented yet.

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
input, and JSON serialization. They run without API keys or real LLM calls.

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

## Repository structure

```text
app/
    __init__.py
    enums.py
    schemas.py
tests/
    .gitkeep
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

# AI Support Ticket Triage API

A planned FastAPI service for converting unstructured IT support tickets into
validated triage results using an LLM and deterministic business rules.

## Current status

TASK-001 initializes the repository: Python packaging, dependencies, development
tools, an importable `app` package, and an environment-variable template.
Domain models, API endpoints, LLM integration, evaluation, Docker, and CI are
scheduled for later tasks and are not implemented yet.

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

The `tests/` directory is reserved for future behavioral tests. At TASK-001,
pytest reports no tests collected (exit code 5). Schema tests start in TASK-002.
Normal automated tests must run without real LLM calls.

## Repository structure

```text
app/
    __init__.py
tests/
    .gitkeep
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

# AGENTS.md

## Project

AI Support Ticket Triage API is a FastAPI-based service that converts
unstructured IT support tickets into validated structured triage results.

For architecture and project decisions, see:

docs/PROJECT_PLAN.md

## Development Guidelines

- Keep the architecture simple.
- Use Pydantic for validation.
- Keep LLM provider logic isolated in `app/llm_client.py`.
- Keep deterministic business rules in the service layer.
- Do not log raw ticket content or secrets.
- Do not call the real OpenAI API from automated tests.
- Add or update tests for behavioral changes.
- Run `pytest` and `ruff check .` before completing changes.

## Scope

Do not introduce RAG, vector databases, agents, databases, or additional
infrastructure unless required by a future feature.
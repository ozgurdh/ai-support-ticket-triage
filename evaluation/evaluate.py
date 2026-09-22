"""Explicit, sequential evaluation through the real service; never runs on import."""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, floor
from pathlib import Path
from statistics import fmean
from time import perf_counter

from pydantic import ConfigDict, ValidationError

from app import service
from app.config import Settings
from app.enums import TicketCategory, TicketPriority
from app.schemas import TicketRequest, TriageResponse

DEFAULT_DATASET = Path(__file__).with_name("eval_tickets.jsonl")


class DatasetTicket(TicketRequest):
    """Validate ticket fields and labels; ignore reference notes and scenario tags."""

    model_config = ConfigDict(extra="ignore")
    expected_category: TicketCategory
    expected_priority: TicketPriority


@dataclass
class EvaluationResult:
    expected_category: TicketCategory
    expected_priority: TicketPriority
    response: TriageResponse | None
    latency_seconds: float
    error_type: str | None = None


def load_dataset(path: Path) -> list[DatasetTicket]:
    """Validate the entire input before making any potentially billable calls."""
    tickets = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                tickets.append(DatasetTicket.model_validate_json(line))
            except ValidationError:
                # Validation messages can contain raw ticket text.
                raise ValueError(
                    f"Invalid dataset row at line {line_number}."
                ) from None
    if not tickets:
        raise ValueError("Dataset contains no tickets.")
    return tickets


def run_evaluation(tickets: Sequence[DatasetTicket]) -> list[EvaluationResult]:
    results = []
    for example in tickets:
        response = None
        error_type = None
        started = perf_counter()
        try:
            # Reference labels, notes, tags, and dataset IDs never reach the model.
            ticket = TicketRequest(
                subject=example.subject, description=example.description
            )
            response = TriageResponse.model_validate(service.triage_ticket(ticket))
        except Exception as error:
            # Continue after provider, validation, or unexpected per-ticket failures.
            # KeyboardInterrupt/SystemExit still interrupt the run normally.
            error_type = type(error).__name__
        results.append(
            EvaluationResult(
                expected_category=example.expected_category,
                expected_priority=example.expected_priority,
                response=response,
                latency_seconds=perf_counter() - started,
                error_type=error_type,
            )
        )
    return results


def _percentile(values: list[float], quantile: float) -> float:
    """Linear interpolation at (n - 1) * quantile; works for a single observation."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower, upper = floor(position), ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def calculate_metrics(results: Sequence[EvaluationResult]) -> dict[str, float | None]:
    total = len(results)
    valid = [result for result in results if result.response is not None]
    critical = [
        result
        for result in results
        if result.expected_priority == TicketPriority.CRITICAL
    ]
    f1_scores = []
    for priority in TicketPriority:
        actual = sum(result.expected_priority == priority for result in results)
        predicted = sum(result.response.priority == priority for result in valid)
        correct = sum(
            result.expected_priority == priority
            and result.response.priority == priority
            for result in valid
        )
        # Equivalent to 2TP / (2TP + FP + FN); failures contribute false negatives.
        f1_scores.append(
            2 * correct / (actual + predicted) if actual + predicted else 0.0
        )
    latencies = [result.latency_seconds for result in results]
    return {
        "category_accuracy": sum(
            result.response.category == result.expected_category for result in valid
        )
        / total
        if total
        else None,
        "priority_accuracy": sum(
            result.response.priority == result.expected_priority for result in valid
        )
        / total
        if total
        else None,
        "priority_macro_f1": fmean(f1_scores) if total else None,
        "critical_recall": sum(
            result.response is not None
            and result.response.priority == TicketPriority.CRITICAL
            for result in critical
        )
        / len(critical)
        if critical
        else None,
        "schema_success_rate": len(valid) / total if total else None,
        "average_latency_seconds": fmean(latencies) if latencies else None,
        "p50_latency_seconds": _percentile(latencies, 0.50) if latencies else None,
        "p95_latency_seconds": _percentile(latencies, 0.95) if latencies else None,
    }


def print_report(results: Sequence[EvaluationResult]) -> None:
    metrics = calculate_metrics(results)
    failures = sum(result.response is None for result in results)
    print(f"Tickets evaluated: {len(results)}")
    print(f"Valid responses: {len(results) - failures}")
    print(f"Failed tickets: {failures}")
    print("\nMetrics include failed tickets; macro F1 uses all four priorities.")
    for label, key in (
        ("Category accuracy", "category_accuracy"),
        ("Priority accuracy", "priority_accuracy"),
        ("Priority macro F1", "priority_macro_f1"),
        ("Critical recall", "critical_recall"),
        ("Schema success rate", "schema_success_rate"),
    ):
        value = metrics[key]
        print(f"{label}: {value:.2%}" if value is not None else f"{label}: N/A")
    print("\nLatency includes all tickets and client retries:")
    for label, key in (
        ("Average latency", "average_latency_seconds"),
        ("P50 latency", "p50_latency_seconds"),
        ("P95 latency", "p95_latency_seconds"),
    ):
        value = metrics[key]
        print(f"{label}: {value:.3f} s" if value is not None else f"{label}: N/A")
    if failures:
        print("\nFailures (ticket number in dataset order):")
        for index, result in enumerate(results, 1):
            if result.error_type:
                print(f"  Ticket {index}: {result.error_type}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate labelled tickets through the real triage service. "
        "Calls the configured OpenAI model unless --validate-only is used."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="JSONL dataset (defaults to evaluation/eval_tickets.jsonl)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate dataset rows without credentials or provider calls",
    )
    args = parser.parse_args(argv)
    try:
        tickets = load_dataset(args.dataset)
    except (OSError, UnicodeError, ValueError) as error:
        message = str(error) if type(error) is ValueError else type(error).__name__
        print(f"Dataset error: {message}", file=sys.stderr)
        return 2
    if args.validate_only:
        print(f"Validated {len(tickets)} tickets. No provider calls were made.")
        return 0
    try:
        Settings()
    except ValidationError:
        print(
            "Invalid LLM configuration; check OPENAI_API_KEY, OPENAI_MODEL, "
            "and OPENAI_TIMEOUT_SECONDS.",
            file=sys.stderr,
        )
        return 2
    results = run_evaluation(tickets)
    print_report(results)
    return 1 if any(result.error_type is not None for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

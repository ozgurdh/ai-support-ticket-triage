"""Offline tests of evaluation mechanics; these are not model evaluation results."""

import json
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from app import llm_client
from app.enums import Department
from app.schemas import LLMClassificationResult, TicketRequest
from evaluation import evaluate

ROW = {
    "subject": "Printer unavailable",
    "description": "The printer does not respond to any jobs.",
    "expected_category": "hardware_device",
    "expected_priority": "medium",
}


def classification(
    priority: str = "medium", category: str = "hardware_device"
) -> LLMClassificationResult:
    return LLMClassificationResult(
        category=category,
        priority=priority,
        summary="Printer unavailable.",
        suggested_action="Check the printer.",
    )


@pytest.fixture(autouse=True)
def classifier(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Mock:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "30")
    mock = Mock(return_value=classification())
    monkeypatch.setattr(llm_client, "classify_ticket", mock)
    return mock


def write_dataset(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "tickets.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def test_real_dataset_validates_without_provider_or_configuration(
    classifier: Mock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Mock(side_effect=AssertionError("Validation must not load credentials"))
    monkeypatch.setattr(evaluate, "Settings", settings)

    assert evaluate.main(["--validate-only"]) == 0

    assert "Validated 50 tickets" in capsys.readouterr().out
    settings.assert_not_called()
    classifier.assert_not_called()


def test_reference_metadata_never_reaches_pipeline(
    tmp_path: Path, classifier: Mock
) -> None:
    path = write_dataset(
        tmp_path,
        [
            {
                **ROW,
                "id": "reference-id",
                "notes": "Never send this reference note",
                "scenario_types": ["prompt_injection"],
            }
        ],
    )
    results = evaluate.run_evaluation(evaluate.load_dataset(path))

    classifier.assert_called_once_with(
        TicketRequest(
            subject=ROW["subject"],
            description=ROW["description"],
        )
    )
    assert results[0].response.department == Department.SERVICE_DESK
    assert results[0].response.needs_human_review is False
    assert results[0].response.ticket_id is None


@pytest.mark.parametrize(
    "bad_line",
    [
        "not JSON",
        "[]",
        "{}",
        json.dumps({**ROW, "expected_category": "unsupported"}),
        json.dumps({**ROW, "expected_priority": "urgent"}),
        json.dumps({**ROW, "description": "short"}),
    ],
)
def test_invalid_dataset_fails_before_any_provider_call(
    tmp_path: Path, classifier: Mock, bad_line: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps(ROW) + "\n" + bad_line, encoding="utf-8")

    assert evaluate.main(["--dataset", str(path)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Dataset error: Invalid dataset row at line 2.\n"
    classifier.assert_not_called()


@pytest.mark.parametrize("content", ["", "\n \n"])
def test_empty_dataset_is_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="Dataset contains no tickets"):
        evaluate.load_dataset(path)


def test_missing_dataset_returns_readable_error(
    tmp_path: Path, classifier: Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    assert evaluate.main(["--dataset", str(tmp_path / "missing.jsonl")]) == 2
    assert "FileNotFoundError" in capsys.readouterr().err
    classifier.assert_not_called()


def test_metrics_count_misclassifications_and_failures(
    classifier: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    tickets = [
        evaluate.DatasetTicket(**{**ROW, "expected_priority": priority})
        for priority in ["low", "medium", "high", "critical", "critical", "high"]
    ]
    classifier.side_effect = [
        classification("low"),
        classification("high"),
        classification("high"),
        classification("critical"),
        classification("low", "software_application"),
        llm_client.LLMTimeoutError("Private details"),
    ]
    monkeypatch.setattr(
        evaluate,
        "perf_counter",
        Mock(
            side_effect=[
                0,
                1,
                1,
                3,
                3,
                6,
                6,
                10,
                10,
                15,
                15,
                21,
            ]
        ),
    )

    results = evaluate.run_evaluation(tickets)
    metrics = evaluate.calculate_metrics(results)

    assert classifier.call_count == 6
    assert metrics == pytest.approx(
        {
            "category_accuracy": 4 / 6,
            "priority_accuracy": 3 / 6,
            # Per-class F1: low=2/3, medium=0, high=1/2, critical=2/3.
            "priority_macro_f1": 11 / 24,
            "critical_recall": 1 / 2,
            "schema_success_rate": 5 / 6,
            "average_latency_seconds": 3.5,
            "p50_latency_seconds": 3.5,
            "p95_latency_seconds": 5.75,
        }
    )
    assert results[-1].error_type == "LLMTimeoutError"
    assert results[-1].latency_seconds == 6


def test_failures_do_not_stop_later_tickets_or_expose_messages(
    classifier: Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    classifier.side_effect = [
        llm_client.LLMTimeoutError("private-timeout"),
        llm_client.LLMClientError(
            "private-api-key",
            diagnostic=(
                "RateLimitError (HTTP 429; code=credit_balance_exhausted; "
                "type=insufficient_quota): Provider credit balance exhausted."
            ),
        ),
        llm_client.LLMResponseError("private-output"),
        RuntimeError("private-description"),
        classification(),
    ]
    results = evaluate.run_evaluation([evaluate.DatasetTicket(**ROW)] * 5)
    evaluate.print_report(results)

    assert classifier.call_count == 5
    assert [result.error_type for result in results] == [
        "LLMTimeoutError",
        "LLMClientError",
        "LLMResponseError",
        "RuntimeError",
        None,
    ]
    output = capsys.readouterr().out
    assert "Failed tickets: 4" in output
    assert "Schema success rate: 20.00%" in output
    assert "Critical recall: N/A" in output
    assert "Ticket 4: RuntimeError" in output
    assert (
        "Ticket 2: LLMClientError — RateLimitError (HTTP 429; "
        "code=credit_balance_exhausted; type=insufficient_quota): "
        "Provider credit balance exhausted."
    ) in output
    assert "private-" not in output


def test_invalid_pipeline_response_counts_as_schema_failure(
    monkeypatch: pytest.MonkeyPatch, classifier: Mock
) -> None:
    monkeypatch.setattr(
        evaluate.service, "triage_ticket", Mock(return_value={"summary": "private"})
    )
    results = evaluate.run_evaluation([evaluate.DatasetTicket(**ROW)])

    assert results[0].error_type == "ValidationError"
    assert results[0].response is None
    assert evaluate.calculate_metrics(results)["schema_success_rate"] == 0
    classifier.assert_not_called()


def test_all_failed_critical_tickets_score_zero(classifier: Mock) -> None:
    classifier.side_effect = llm_client.LLMTimeoutError("private")
    results = evaluate.run_evaluation(
        [evaluate.DatasetTicket(**{**ROW, "expected_priority": "critical"})]
    )
    metrics = evaluate.calculate_metrics(results)

    for key in (
        "category_accuracy",
        "priority_accuracy",
        "priority_macro_f1",
        "critical_recall",
        "schema_success_rate",
    ):
        assert metrics[key] == 0
    assert metrics["p50_latency_seconds"] == metrics["p95_latency_seconds"]
    assert metrics["p50_latency_seconds"] == metrics["average_latency_seconds"]


def test_empty_results_have_no_fabricated_metrics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert all(value is None for value in evaluate.calculate_metrics([]).values())
    evaluate.print_report([])
    output = capsys.readouterr().out
    assert "Tickets evaluated: 0" in output
    assert output.count("N/A") == 8


@pytest.mark.parametrize("fail", [False, True])
def test_cli_reports_results_and_exit_status(
    tmp_path: Path, classifier: Mock, capsys: pytest.CaptureFixture[str], fail: bool
) -> None:
    path = write_dataset(tmp_path, [ROW, ROW])
    if fail:
        classifier.side_effect = [
            llm_client.LLMClientError("private"),
            classification(),
        ]

    assert evaluate.main(["--dataset", str(path)]) == (1 if fail else 0)

    assert (
        classifier.call_args_list
        == [call(TicketRequest(subject=ROW["subject"], description=ROW["description"]))]
        * 2
    )
    output = capsys.readouterr().out
    for label in (
        "Tickets evaluated: 2",
        "Category accuracy:",
        "Priority accuracy:",
        "Priority macro F1:",
        "Critical recall:",
        "Schema success rate:",
        "Average latency:",
        "P50 latency:",
        "P95 latency:",
    ):
        assert label in output


@pytest.mark.parametrize("limit,expected", [(1, 1), (2, 2), (5, 3)])
def test_cli_limit_evaluates_first_tickets_only(
    tmp_path: Path,
    classifier: Mock,
    capsys: pytest.CaptureFixture[str],
    limit: int,
    expected: int,
) -> None:
    rows = [{**ROW, "subject": f"Ticket {index}"} for index in range(1, 4)]
    path = write_dataset(tmp_path, rows)

    assert evaluate.main(["--dataset", str(path), "--limit", str(limit)]) == 0

    assert classifier.call_args_list == [
        call(TicketRequest(subject=row["subject"], description=row["description"]))
        for row in rows[:expected]
    ]
    assert f"Tickets evaluated: {expected}" in capsys.readouterr().out


@pytest.mark.parametrize("limit", ["0", "-1", "abc"])
def test_cli_limit_rejects_non_positive_or_non_integer_values(
    classifier: Mock, capsys: pytest.CaptureFixture[str], limit: str
) -> None:
    with pytest.raises(SystemExit) as raised:
        evaluate.main(["--limit", limit])

    assert raised.value.code == 2
    assert "--limit" in capsys.readouterr().err
    classifier.assert_not_called()


def test_invalid_configuration_exits_before_calls(
    monkeypatch: pytest.MonkeyPatch,
    classifier: Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")
    assert evaluate.main([]) == 2
    assert "Invalid LLM configuration" in capsys.readouterr().err
    classifier.assert_not_called()


def test_user_interrupt_is_not_swallowed(classifier: Mock) -> None:
    classifier.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        evaluate.run_evaluation([evaluate.DatasetTicket(**ROW)] * 2)
    classifier.assert_called_once()

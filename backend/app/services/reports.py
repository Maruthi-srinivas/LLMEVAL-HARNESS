"""Finished-run reports. One CSV row per case and metric."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from backend.app.errors import APIError
from backend.app.models import EvaluationRun
from backend.app.services.evaluations import case_results

_TERMINAL = {"completed", "partial", "cancelled"}


def assert_reportable(run: EvaluationRun) -> None:
    if run.status not in _TERMINAL:
        raise APIError(409, "validation_error", "Report is available after the run finishes")


def json_report(session, run: EvaluationRun) -> dict:
    assert_reportable(run)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": str(run.id),
        "status": run.status,
        "snapshot": run.snapshot,
        "summary": run.summary,
        "progress": run.progress,
        "started_at": None if run.started_at is None else run.started_at.isoformat(),
        "finished_at": None if run.finished_at is None else run.finished_at.isoformat(),
        "cases": case_results(session, run.id),
    }


def csv_report(session, run: EvaluationRun) -> str:
    body = json_report(session, run)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "case_key",
            "execution_status",
            "error_category",
            "error_detail",
            "expected_output",
            "output",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "tags",
            "metric_name",
            "metric_status",
            "score",
            "explanation",
        ],
    )
    writer.writeheader()
    for case in body["cases"]:
        usage = case.get("token_usage") or {}
        base = {
            "case_key": case["case_key"],
            "execution_status": case["execution_status"],
            "error_category": case.get("error_category") or "",
            "error_detail": case.get("error_detail") or "",
            "expected_output": case.get("expected_output") or "",
            "output": case.get("output") or "",
            "latency_ms": "" if case.get("latency_ms") is None else case["latency_ms"],
            "input_tokens": usage.get("input_tokens", ""),
            "output_tokens": usage.get("output_tokens", ""),
            "tags": ",".join(case.get("tags") or []),
        }
        metrics = case.get("metrics") or []
        if not metrics:
            writer.writerow({**base, "metric_name": "", "metric_status": "", "score": "", "explanation": ""})
            continue
        for metric in metrics:
            writer.writerow(
                {
                    **base,
                    "metric_name": metric["metric_name"],
                    "metric_status": metric["status"],
                    "score": "" if metric["score"] is None else metric["score"],
                    "explanation": metric.get("explanation") or "",
                }
            )
    return buffer.getvalue()

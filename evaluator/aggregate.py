"""Summaries keep execution errors out of quality-failure counts."""

from __future__ import annotations

import math

from evaluator.types import CaseExecution


def nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(percentile / 100 * len(ordered))
    index = min(max(rank, 1), len(ordered)) - 1
    return ordered[index]


def summarize(results: list[CaseExecution]) -> tuple[str, dict]:
    execution_errors = sum(1 for result in results if result.execution_status == "execution_error")
    succeeded = len(results) - execution_errors
    status = "partial" if execution_errors else "completed"
    pass_counts: dict[str, int] = {}
    fail_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    for result in results:
        for score in result.scores:
            bucket = {"passed": pass_counts, "failed": fail_counts, "metric_error": error_counts}.get(
                score.status
            )
            if bucket is None:
                continue
            bucket[score.metric_name] = bucket.get(score.metric_name, 0) + 1
    latencies = [
        result.latency_ms
        for result in results
        if result.execution_status == "succeeded" and result.latency_ms is not None
    ]
    case_count = len(results)
    summary = {
        "case_count": case_count,
        "succeeded": succeeded,
        "execution_errors": execution_errors,
        "error_rate": (execution_errors / case_count) if case_count else 0.0,
        "metric_pass_counts": pass_counts,
        "metric_fail_counts": fail_counts,
        "metric_error_counts": error_counts,
        "latency_ms_median": nearest_rank(latencies, 50),
        "latency_ms_p95": nearest_rank(latencies, 95),
    }
    return status, summary

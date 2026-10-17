"""Scripted target used by tests and the sample run."""

from __future__ import annotations

from typing import Any, Protocol

from evaluator.text import normalize_text
from evaluator.types import EvaluationCase, TargetResult


class TargetAdapter(Protocol):
    async def invoke(self, input_text: str, metadata: dict[str, Any]) -> TargetResult: ...


def success_result(output: str, latency_ms: float = 20.0) -> TargetResult:
    return TargetResult(
        output=output,
        context=[],
        metadata={
            "latency_ms": latency_ms,
            "token_usage": {
                "input_tokens": 12,
                "output_tokens": max(1, len(output.split())),
            },
        },
    )


def timeout_result() -> TargetResult:
    return TargetResult(
        output="",
        context=[],
        metadata={"latency_ms": 1000.0, "token_usage": {}},
        error_category="timeout",
        error_detail="Mock target timed out",
    )


def rate_limit_result() -> TargetResult:
    return TargetResult(
        output="",
        context=[],
        metadata={"latency_ms": 5.0, "token_usage": {}},
        error_category="rate_limit",
        error_detail="Mock target was rate limited",
    )


class MockTargetAdapter:
    def __init__(self, scripts: dict[str, TargetResult] | None = None):
        self.scripts = scripts or {}
        self.calls: list[str] = []

    @classmethod
    def for_sample(cls, cases: list[EvaluationCase]) -> MockTargetAdapter:
        scripts: dict[str, TargetResult] = {}
        by_key = {case.case_key: case for case in cases}
        for index, case in enumerate(cases):
            scripts[case.case_key] = success_result(case.expected_output, latency_ms=10.0 * (index + 1))
        if "qa-002" in by_key:
            scripts["qa-002"] = success_result(
                normalize_text(by_key["qa-002"].expected_output),
                latency_ms=20.0,
            )
        if "qa-003" in by_key:
            scripts["qa-003"] = success_result("Refunds are not available.", latency_ms=30.0)
        if "qa-err" in by_key:
            scripts["qa-err"] = timeout_result()
        return cls(scripts)

    async def invoke(self, input_text: str, metadata: dict[str, Any]) -> TargetResult:
        case_key = str(metadata.get("case_key", ""))
        self.calls.append(case_key)
        if case_key in self.scripts:
            return self.scripts[case_key]
        return success_result(input_text, latency_ms=1.0)

"""Shared evaluation records. No HTTP types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvaluationCase:
    case_key: str
    input_text: str
    expected_output: str
    context: str | None = None
    tags: tuple[str, ...] = ()
    json_schema: dict[str, Any] | None = None
    line_number: int = 0

    def has_field(self, name: str) -> bool:
        if name == "expected_output":
            return self.expected_output != ""
        if name == "json_schema":
            return self.json_schema is not None
        if name == "input":
            return self.input_text != ""
        if name == "context":
            return self.context is not None
        raise KeyError(name)


@dataclass
class TargetResult:
    output: str
    context: list[str]
    metadata: dict[str, Any]
    error_category: str | None = None
    error_detail: str | None = None


@dataclass
class EvaluationScore:
    metric_name: str
    score: float | None
    passed: bool | None
    explanation: str
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "failed"


@dataclass
class CaseExecution:
    case_key: str
    execution_status: str
    output: str | None
    error_category: str | None
    error_detail: str | None
    latency_ms: float | None
    token_usage: dict[str, Any]
    scores: list[EvaluationScore]

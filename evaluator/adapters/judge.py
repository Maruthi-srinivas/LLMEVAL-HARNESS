"""Scripted judge. It never contacts a model provider."""

from __future__ import annotations

import json
from typing import Any

from evaluator.types import TargetResult

JUDGE_MODEL = "mock-judge"
RUBRIC_VERSION = "1"


class MockJudgeAdapter:
    async def invoke(self, input_text: str, metadata: dict[str, Any]) -> TargetResult:
        case_key = str(metadata.get("case_key", ""))
        metric = str(metadata.get("metric", ""))
        behavior = str(metadata.get("behavior") or "")
        if case_key == "release-main" and behavior in {"release_baseline", "release_candidate"}:
            if behavior == "release_baseline" and metric == "correctness":
                payload = {
                    "metric": metric,
                    "score": 0.4,
                    "passed": False,
                    "explanation": "The baseline answer misses part of the expected account status.",
                    "evidence": ["Scripted baseline correctness."],
                }
            elif behavior == "release_baseline" and metric == "faithfulness":
                payload = {
                    "metric": metric,
                    "score": 0.9,
                    "passed": True,
                    "explanation": "The account summary supports the balance statement.",
                    "evidence": ["doc-1 states the balance."],
                }
            elif behavior == "release_candidate" and metric == "correctness":
                payload = {
                    "metric": metric,
                    "score": 0.95,
                    "passed": True,
                    "explanation": "The candidate answer covers the account status.",
                    "evidence": ["Scripted candidate correctness."],
                }
            elif behavior == "release_candidate" and metric == "faithfulness":
                payload = {
                    "metric": metric,
                    "score": 0.1,
                    "passed": False,
                    "explanation": "The refund claim is not supported by the retrieved document.",
                    "evidence": ["doc-9 does not state that a refund was approved."],
                }
            else:
                payload = None
            if payload is not None:
                return TargetResult(
                    output=json.dumps(payload),
                    context=[],
                    metadata={"latency_ms": 5.0, "token_usage": {"input_tokens": 8, "output_tokens": 4}},
                )
        if case_key == "case-bad-judge" and metric == "faithfulness":
            return TargetResult(output="not-json", context=[], metadata={"latency_ms": 5.0, "token_usage": {}})
        if case_key == "case-judge-timeout" and metric == "faithfulness":
            return TargetResult(
                output="",
                context=[],
                metadata={"latency_ms": 1000.0, "token_usage": {}},
                error_category="timeout",
                error_detail="Mock judge timed out",
            )
        if case_key == "case-unsupported" and metric == "faithfulness":
            payload = {
                "metric": metric,
                "score": 0.1,
                "passed": False,
                "explanation": "The claim is not supported by the retrieved evidence.",
                "evidence": ["doc-1 does not state the claim."],
            }
        elif metric == "task_completion" and case_key in {"agent-ok", "agent-forbidden"}:
            payload = {
                "metric": metric,
                "score": 1.0,
                "passed": True,
                "explanation": "The scripted task finished.",
                "evidence": [case_key],
            }
        else:
            payload = {
                "metric": metric,
                "score": 0.9,
                "passed": True,
                "explanation": "The answer meets the rubric.",
                "evidence": ["Scripted judge evidence."],
            }
        return TargetResult(
            output=json.dumps(payload),
            context=[],
            metadata={"latency_ms": 5.0, "token_usage": {"input_tokens": 8, "output_tokens": 4}},
        )

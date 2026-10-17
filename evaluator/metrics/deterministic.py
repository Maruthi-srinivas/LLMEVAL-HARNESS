"""Deterministic evaluators. Each one declares the case fields it requires."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, UnknownType, ValidationError

from evaluator.text import normalize_text
from evaluator.types import EvaluationCase, EvaluationScore, TargetResult


class Evaluator:
    name = "evaluator"
    version = "1"
    required_fields: frozenset[str] = frozenset()

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        raise NotImplementedError


def _quality(name: str, passed: bool, explanation: str, score: float | None = None) -> EvaluationScore:
    return EvaluationScore(
        metric_name=name,
        score=1.0 if passed and score is None else (0.0 if score is None else score),
        passed=passed,
        explanation=explanation,
        status="passed" if passed else "failed",
    )


def _metric_error(name: str, explanation: str) -> EvaluationScore:
    return EvaluationScore(
        metric_name=name,
        score=None,
        passed=None,
        explanation=explanation,
        status="metric_error",
    )


class ExactMatchEvaluator(Evaluator):
    name = "exact_match"
    required_fields = frozenset({"expected_output"})

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        passed = prediction.output == case.expected_output
        explanation = "Output matches the expected text." if passed else "Output differs from the expected text."
        return _quality(self.name, passed, explanation)


class NormalizedMatchEvaluator(Evaluator):
    name = "normalized_match"
    required_fields = frozenset({"expected_output"})

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        passed = normalize_text(prediction.output) == normalize_text(case.expected_output)
        explanation = (
            "Output matches after case folding and whitespace collapsing."
            if passed
            else "Output differs after case folding and whitespace collapsing."
        )
        return _quality(self.name, passed, explanation)


class TokenF1Evaluator(Evaluator):
    name = "token_f1"
    required_fields = frozenset({"expected_output"})

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        score = token_f1(case.expected_output, prediction.output)
        passed = score == 1.0
        return EvaluationScore(
            metric_name=self.name,
            score=score,
            passed=passed,
            explanation=f"Whitespace token F1 is {score:.4f}. A score of 1 is required to pass.",
            status="passed" if passed else "failed",
        )


class JsonSchemaEvaluator(Evaluator):
    name = "json_schema"
    required_fields = frozenset({"json_schema"})

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        assert case.json_schema is not None
        try:
            instance = json.loads(prediction.output)
        except json.JSONDecodeError:
            return _quality(self.name, False, "Output is not valid JSON.")
        try:
            Draft202012Validator(case.json_schema).validate(instance)
        except (SchemaError, UnknownType) as exc:
            return _metric_error(self.name, f"JSON Schema is invalid: {exc}")
        except ValidationError as exc:
            return _quality(self.name, False, f"Output failed JSON Schema validation: {exc.message}")
        return _quality(self.name, True, "Output satisfies the JSON Schema.")


class LatencyEvaluator(Evaluator):
    name = "latency"
    required_fields = frozenset()

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        latency = prediction.metadata.get("latency_ms")
        if not isinstance(latency, (int, float)) or isinstance(latency, bool):
            return _metric_error(self.name, "Target metadata did not include latency_ms.")
        return EvaluationScore(
            metric_name=self.name,
            score=float(latency),
            passed=True,
            explanation=f"Target latency was {float(latency):.3f} ms.",
            status="passed",
        )


class TokenUsageEvaluator(Evaluator):
    name = "token_usage"
    required_fields = frozenset()

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        usage = prediction.metadata.get("token_usage")
        if not isinstance(usage, dict):
            return _metric_error(self.name, "Target metadata did not include token_usage.")
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if not _is_count(input_tokens) or not _is_count(output_tokens):
            return _metric_error(self.name, "token_usage is missing numeric input_tokens or output_tokens.")
        total = float(input_tokens) + float(output_tokens)
        return EvaluationScore(
            metric_name=self.name,
            score=total,
            passed=True,
            explanation=f"Token usage was {int(input_tokens)} input and {int(output_tokens)} output.",
            metadata={"input_tokens": input_tokens, "output_tokens": output_tokens},
            status="passed",
        )


class ErrorRateEvaluator(Evaluator):
    name = "error_rate"
    required_fields = frozenset()

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        if prediction.error_category:
            return EvaluationScore(
                metric_name=self.name,
                score=None,
                passed=None,
                explanation="Execution failed. This case is not a quality failure.",
                status="skipped",
            )
        return EvaluationScore(
            metric_name=self.name,
            score=0.0,
            passed=True,
            explanation="Invocation succeeded. This case does not contribute an execution error.",
            status="passed",
        )


def token_f1(expected: str, actual: str) -> float:
    expected_tokens = expected.split()
    actual_tokens = actual.split()
    if not expected_tokens and not actual_tokens:
        return 1.0
    if not expected_tokens or not actual_tokens:
        return 0.0
    overlap = sum((Counter(expected_tokens) & Counter(actual_tokens)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(actual_tokens)
    recall = overlap / len(expected_tokens)
    return 2 * precision * recall / (precision + recall)


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def default_sample_evaluators() -> list[Evaluator]:
    return [
        ExactMatchEvaluator(),
        NormalizedMatchEvaluator(),
        TokenF1Evaluator(),
        LatencyEvaluator(),
        TokenUsageEvaluator(),
        ErrorRateEvaluator(),
    ]

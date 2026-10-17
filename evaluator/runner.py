"""Execute cases against an adapter and score successful predictions only."""

from __future__ import annotations

from evaluator.aggregate import summarize
from evaluator.metrics.deterministic import Evaluator
from evaluator.types import CaseExecution, EvaluationCase, TargetResult


class IncompatibleConfiguration(Exception):
    pass


KNOWN_FIELDS = frozenset({"expected_output", "json_schema", "input", "context"})


def validate_configuration(cases: list[EvaluationCase], evaluators: list[Evaluator]) -> None:
    if not cases:
        raise IncompatibleConfiguration("Dataset has no cases")
    if not evaluators:
        raise IncompatibleConfiguration("At least one evaluator is required")
    for evaluator in evaluators:
        unknown = set(evaluator.required_fields) - KNOWN_FIELDS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise IncompatibleConfiguration(f"{evaluator.name} declares unknown fields: {names}")
        for case in cases:
            missing = [field for field in sorted(evaluator.required_fields) if not case.has_field(field)]
            if missing:
                raise IncompatibleConfiguration(
                    f"{evaluator.name} requires {', '.join(missing)} on case {case.case_key}"
                )


def _latency(prediction: TargetResult) -> float | None:
    latency = prediction.metadata.get("latency_ms")
    if isinstance(latency, (int, float)) and not isinstance(latency, bool):
        return float(latency)
    return None


def _usage(prediction: TargetResult) -> dict:
    usage = prediction.metadata.get("token_usage")
    return usage if isinstance(usage, dict) else {}


async def _execute_case(case: EvaluationCase, adapter, evaluators: list[Evaluator]) -> CaseExecution:
    prediction = await adapter.invoke(case.input_text, {"case_key": case.case_key})
    if prediction.error_category:
        return CaseExecution(
            case_key=case.case_key,
            execution_status="execution_error",
            output=None,
            error_category=prediction.error_category,
            error_detail=(prediction.error_detail or "")[:500],
            latency_ms=_latency(prediction),
            token_usage={},
            scores=[],
        )
    scores = []
    for evaluator in evaluators:
        score = evaluator.evaluate(case, prediction)
        if score.status == "skipped":
            continue
        scores.append(score)
    return CaseExecution(
        case_key=case.case_key,
        execution_status="succeeded",
        output=prediction.output,
        error_category=None,
        error_detail=None,
        latency_ms=_latency(prediction),
        token_usage=_usage(prediction),
        scores=scores,
    )


async def execute(cases: list[EvaluationCase], adapter, evaluators: list[Evaluator]) -> list[CaseExecution]:
    validate_configuration(cases, evaluators)
    results = []
    for case in cases:
        results.append(await _execute_case(case, adapter, evaluators))
    return results


def final_status(results: list[CaseExecution]) -> tuple[str, dict]:
    return summarize(results)

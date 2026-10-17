import asyncio

import pytest

from evaluator.adapters.mock import MockTargetAdapter, success_result
from evaluator.aggregate import nearest_rank, summarize
from evaluator.metrics.deterministic import (
    ErrorRateEvaluator,
    ExactMatchEvaluator,
    JsonSchemaEvaluator,
    LatencyEvaluator,
    NormalizedMatchEvaluator,
    TokenF1Evaluator,
    TokenUsageEvaluator,
    token_f1,
)
from evaluator.runner import IncompatibleConfiguration, execute
from evaluator.status import InvalidTransition, transition
from evaluator.text import normalize_text
from evaluator.types import CaseExecution, EvaluationCase, EvaluationScore, TargetResult


def _case(**overrides) -> EvaluationCase:
    values = {
        "case_key": "c1",
        "input_text": "question",
        "expected_output": "expected answer",
    }
    values.update(overrides)
    return EvaluationCase(**values)


def test_exact_and_normalized_match():
    case = _case(expected_output="Hello   World")
    exact = ExactMatchEvaluator().evaluate(case, success_result("hello world"))
    normalized = NormalizedMatchEvaluator().evaluate(case, success_result("hello world"))
    assert exact.status == "failed"
    assert exact.score == 0.0
    assert normalized.status == "passed"
    assert normalize_text("Hello   World") == "hello world"


def test_exact_match_is_strict():
    case = _case(expected_output="Same")
    score = ExactMatchEvaluator().evaluate(case, success_result("Same"))
    assert score.status == "passed"
    assert score.score == 1.0


def test_token_f1_boundaries():
    assert token_f1("", "") == 1.0
    assert token_f1("alpha", "") == 0.0
    assert token_f1("", "alpha") == 0.0
    assert token_f1("a b c", "b c d") == pytest.approx(2 / 3)
    partial = TokenF1Evaluator().evaluate(_case(expected_output="a b c"), success_result("b c d"))
    assert partial.status == "failed"
    assert partial.score == pytest.approx(2 / 3)
    perfect = TokenF1Evaluator().evaluate(_case(expected_output="a b"), success_result("a b"))
    assert perfect.status == "passed"


def test_json_schema_draft_2020_12():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    case = _case(json_schema=schema, expected_output='{"status":"ok"}')
    evaluator = JsonSchemaEvaluator()
    assert evaluator.evaluate(case, success_result('{"status":"ok"}')).status == "passed"
    assert evaluator.evaluate(case, success_result('{"status":1}')).status == "failed"
    assert evaluator.evaluate(case, success_result("not-json")).status == "failed"
    broken = _case(json_schema={"type": "not-a-real-type"}, expected_output="{}")
    assert evaluator.evaluate(broken, success_result("{}")).status == "metric_error"


def test_latency_and_token_usage_metadata():
    case = _case()
    missing = TargetResult(output="x", context=[], metadata={})
    assert LatencyEvaluator().evaluate(case, missing).status == "metric_error"
    assert TokenUsageEvaluator().evaluate(case, missing).status == "metric_error"
    present = success_result("x", latency_ms=12.5)
    latency = LatencyEvaluator().evaluate(case, present)
    usage = TokenUsageEvaluator().evaluate(case, present)
    assert latency.status == "passed"
    assert latency.score == 12.5
    assert usage.status == "passed"
    assert usage.score == 13


def test_error_rate_does_not_treat_timeouts_as_quality_failures():
    case = _case()
    skipped = ErrorRateEvaluator().evaluate(
        case,
        TargetResult(output="", context=[], metadata={}, error_category="timeout", error_detail="timed out"),
    )
    assert skipped.status == "skipped"
    assert skipped.passed is None
    succeeded = ErrorRateEvaluator().evaluate(case, success_result("ok"))
    assert succeeded.status == "passed"
    assert succeeded.score == 0.0


def test_summary_keeps_execution_errors_out_of_quality_counts():
    results = [
        CaseExecution(
            case_key="ok",
            execution_status="succeeded",
            output="nope",
            error_category=None,
            error_detail=None,
            latency_ms=10,
            token_usage={"input_tokens": 1, "output_tokens": 1},
            scores=[
                EvaluationScore("exact_match", 0.0, False, "mismatch", status="failed"),
            ],
        ),
        CaseExecution(
            case_key="err",
            execution_status="execution_error",
            output=None,
            error_category="timeout",
            error_detail="timed out",
            latency_ms=1000,
            token_usage={},
            scores=[],
        ),
    ]
    status, summary = summarize(results)
    assert status == "partial"
    assert summary["execution_errors"] == 1
    assert summary["metric_fail_counts"] == {"exact_match": 1}
    assert summary["metric_error_counts"] == {}
    assert summary["case_count"] == 2
    assert summary["error_rate"] == 0.5
    assert summary["latency_ms_median"] == 10
    assert summary["latency_ms_p95"] == 10
    assert nearest_rank([10, 20, 30, 40, 50], 95) == 50
    assert nearest_rank([], 95) is None


def test_run_state_transitions():
    assert transition("pending", "start") == "running"
    assert transition("running", "succeed") == "completed"
    assert transition("running", "partial") == "partial"
    with pytest.raises(InvalidTransition):
        transition("pending", "succeed")
    with pytest.raises(InvalidTransition):
        transition("completed", "start")
    with pytest.raises(InvalidTransition):
        transition("partial", "succeed")


def test_incompatible_evaluator_is_rejected_before_the_adapter_is_called():
    class BoomAdapter:
        async def invoke(self, input_text, metadata):
            raise AssertionError("adapter should not be called")

    cases = [_case(case_key="plain", json_schema=None)]
    with pytest.raises(IncompatibleConfiguration, match="json_schema"):
        asyncio.run(execute(cases, BoomAdapter(), [JsonSchemaEvaluator()]))


def test_sample_mock_splits_timeout_from_wrong_answer():
    from evaluator.datasets.loader import default_sample_path, load_jsonl

    cases = load_jsonl(default_sample_path())
    adapter = MockTargetAdapter.for_sample(cases)
    by_key = {case.case_key: case for case in cases}

    async def collect():
        timeout = await adapter.invoke(by_key["qa-err"].input_text, {"case_key": "qa-err"})
        changed = await adapter.invoke(by_key["qa-002"].input_text, {"case_key": "qa-002"})
        wrong = await adapter.invoke(by_key["qa-003"].input_text, {"case_key": "qa-003"})
        exact = await adapter.invoke(by_key["qa-001"].input_text, {"case_key": "qa-001"})
        return timeout, changed, wrong, exact

    timeout, changed, wrong, exact = asyncio.run(collect())
    assert timeout.error_category == "timeout"
    assert changed.output != by_key["qa-002"].expected_output
    assert normalize_text(changed.output) == normalize_text(by_key["qa-002"].expected_output)
    assert wrong.output != by_key["qa-003"].expected_output
    assert exact.output == by_key["qa-001"].expected_output


def test_execute_skips_scores_when_the_target_times_out():
    cases = [_case(case_key="qa-err")]
    adapter = MockTargetAdapter({"qa-err": TargetResult(output="", context=[], metadata={}, error_category="timeout", error_detail="timed out")})
    results = asyncio.run(execute(cases, adapter, [ExactMatchEvaluator(), ErrorRateEvaluator()]))
    assert results[0].execution_status == "execution_error"
    assert results[0].scores == []
    assert adapter.calls == ["qa-err"]

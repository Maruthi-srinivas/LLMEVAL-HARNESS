"""Tool-use metrics. A missing trace is a metric error, not a wrong answer."""

from __future__ import annotations

from evaluator.metrics.deterministic import _metric_error, _quality
from evaluator.types import EvaluationCase, EvaluationScore, TargetResult


def _steps(prediction: TargetResult) -> list[dict] | None:
    trace = prediction.metadata.get("trace")
    if not isinstance(trace, dict) or not isinstance(trace.get("steps"), list):
        return None
    return [step for step in trace["steps"] if isinstance(step, dict)]


def _tool_steps(steps: list[dict]) -> list[dict]:
    return [step for step in steps if step.get("kind") == "tool"]


class ToolSelectionEvaluator:
    name = "tool_selection"
    version = "1"
    required_fields = frozenset({"expected_tools"})
    config_schema = {"type": "object", "additionalProperties": False, "properties": {}}
    score_range = (0.0, 1.0)
    failure_behavior = (
        "A quality failure means the called tools differ from the expected tools. "
        "metric_error means the metric could not be computed and is not a wrong answer."
    )

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        steps = _steps(prediction)
        if steps is None:
            return _metric_error(self.name, "The case has no agent trace")
        called = {str(step.get("name")) for step in _tool_steps(steps)}
        expected = {str(tool.get("name")) for tool in case.expected_tools}
        return _quality(self.name, called == expected, f"Called {sorted(called)}; expected {sorted(expected)}")


class ToolArgumentsEvaluator:
    name = "tool_arguments"
    version = "1"
    required_fields = frozenset({"expected_tools"})
    config_schema = {"type": "object", "additionalProperties": False, "properties": {}}
    score_range = (0.0, 1.0)
    failure_behavior = (
        "A quality failure means a tool call did not use the expected arguments. "
        "metric_error means the metric could not be computed and is not a wrong answer."
    )

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        steps = _steps(prediction)
        if steps is None:
            return _metric_error(self.name, "The case has no agent trace")
        expected = {str(tool.get("name")): tool.get("arguments") or {} for tool in case.expected_tools}
        calls = _tool_steps(steps)
        matched = [step for step in calls if step.get("arguments", step.get("input")) == expected.get(str(step.get("name")))]
        passed = len(calls) > 0 and len(matched) == len(calls) and len(matched) == len(expected)
        return _quality(self.name, passed, f"{len(matched)} of {len(expected)} expected tool calls used the recorded arguments")


class ToolPermissionEvaluator:
    name = "tool_permission"
    version = "1"
    required_fields = frozenset({"allowed_tools"})
    config_schema = {"type": "object", "additionalProperties": False, "properties": {}}
    score_range = (0.0, 1.0)
    failure_behavior = (
        "A quality failure means the agent called a tool outside the case allow list. "
        "metric_error means the metric could not be computed and is not a wrong answer."
    )

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        steps = _steps(prediction)
        if steps is None:
            return _metric_error(self.name, "The case has no agent trace")
        allowed = set(case.allowed_tools)
        called = [str(step.get("name")) for step in _tool_steps(steps)]
        forbidden = sorted({name for name in called if name not in allowed})
        return _quality(
            self.name,
            not forbidden and len(called) > 0,
            "Every called tool is allowed" if not forbidden else f"Forbidden tools: {', '.join(forbidden)}",
        )


class ToolRecoveryEvaluator:
    name = "tool_recovery"
    version = "1"
    required_fields = frozenset()
    config_schema = {"type": "object", "additionalProperties": False, "properties": {}}
    score_range = (0.0, 1.0)
    failure_behavior = (
        "A quality failure means a tool error was not retried. "
        "metric_error means the metric could not be computed and is not a wrong answer."
    )

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        steps = _steps(prediction)
        if steps is None:
            return _metric_error(self.name, "The case has no agent trace")
        calls = _tool_steps(steps)
        failed = [step for step in calls if step.get("error")]
        recovered = True
        for step in failed:
            later = calls[calls.index(step) + 1 :]
            if not any(item.get("name") == step.get("name") and not item.get("error") for item in later):
                recovered = False
        return _quality(self.name, recovered, "Tool errors were retried" if recovered else "A tool error was not retried")


class ToolUnnecessaryEvaluator:
    name = "tool_unnecessary"
    version = "1"
    required_fields = frozenset({"expected_tools"})
    config_schema = {"type": "object", "additionalProperties": False, "properties": {}}
    score_range = (0.0, 1.0)
    failure_behavior = (
        "A quality failure means a tool was repeated or was not expected. "
        "metric_error means the metric could not be computed and is not a wrong answer."
    )

    def evaluate(self, case: EvaluationCase, prediction: TargetResult) -> EvaluationScore:
        steps = _steps(prediction)
        if steps is None:
            return _metric_error(self.name, "The case has no agent trace")
        expected = {str(tool.get("name")) for tool in case.expected_tools}
        names = [str(step.get("name")) for step in _tool_steps(steps)]
        repeated = len(names) != len(set(names))
        outside = [name for name in names if name not in expected]
        passed = not repeated and not outside and len(names) > 0
        return _quality(self.name, passed, "Every tool call was expected once" if passed else "A tool call was repeated or unexpected")

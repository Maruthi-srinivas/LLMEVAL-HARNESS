"""Test-only execution. The product evaluation route does not call this."""

from __future__ import annotations

import asyncio

from backend.app.settings import allow_inline_execution
from evaluator.adapters.mock import MockTargetAdapter
from evaluator.metrics.deterministic import Evaluator
from evaluator.runner import execute
from evaluator.types import CaseExecution, EvaluationCase


class InlineExecutionDisabled(Exception):
    pass


def execute_inline(cases: list[EvaluationCase], evaluators: list[Evaluator]) -> list[CaseExecution]:
    if not allow_inline_execution():
        raise InlineExecutionDisabled("Inline execution is disabled")
    return asyncio.run(execute(cases, MockTargetAdapter(), evaluators))

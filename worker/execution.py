"""Claim cases in Postgres and execute them one at a time."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.db import session_scope
from backend.app.models import CaseAttempt, CaseResult, EvaluationRun, MetricResult, TargetConfig, TestCase
from backend.app.services.evaluations import _REGISTRY
from evaluator.adapters.mock import MockTargetAdapter, rate_limit_result, success_result, timeout_result
from evaluator.runner import _execute_case
from evaluator.status import transition
from evaluator.store import persist_case
from evaluator.types import EvaluationCase, TargetResult
from worker.policy import completion_status

BATCH_SIZE = 10
_TERMINAL = {"completed", "partial", "cancelled"}


def process_run(run_id: str, max_batches: int | None = None) -> None:
    """Execute claimed batches until the run is terminal or the batch cap is hit."""
    completed_batches = 0
    while max_batches is None or completed_batches < max_batches:
        claimed = _claim_batch(run_id)
        if claimed is None:
            return
        if not claimed:
            _finalize(run_id)
            return
        for index, test_case_id in enumerate(claimed):
            if _is_cancelled(run_id):
                _release_claims(run_id, claimed[index:])
                _finalize(run_id)
                return
            _execute_claimed(run_id, test_case_id)
        completed_batches += 1
        if _finalize(run_id):
            return


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _claim_batch(run_id: str) -> list[uuid.UUID] | None:
    with session_scope() as session:
        run = session.get(EvaluationRun, uuid.UUID(run_id))
        if run is None or run.status in {"completed", "partial"}:
            return None
        now = _now()
        if run.status == "queued":
            run.status = transition(run.status, "start")
            run.started_at = now
        elif run.status == "cancelled":
            return []
        elif run.status != "running":
            return None
        run.heartbeat_at = now
        total = _case_count(session, run.dataset_version_id)
        _write_progress(session, run, total)
        if _unresolved(session, run.id, total) == 0 and total > 0:
            return []
        if run.status == "cancelled":
            return []
        claimed_ids = select(CaseAttempt.test_case_id).where(CaseAttempt.run_id == run.id)
        rows = session.scalars(
            select(TestCase)
            .where(
                TestCase.dataset_version_id == run.dataset_version_id,
                TestCase.id.not_in(claimed_ids),
            )
            .order_by(TestCase.case_key)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            session.add(
                CaseAttempt(
                    run_id=run.id,
                    test_case_id=row.id,
                    status="claimed",
                    heartbeat_at=now,
                )
            )
        session.flush()
        return [row.id for row in rows]


def _execute_claimed(run_id: str, test_case_id: uuid.UUID) -> None:
    with session_scope() as session:
        run = session.get(EvaluationRun, uuid.UUID(run_id))
        case = session.get(TestCase, test_case_id)
        attempt = session.scalar(
            select(CaseAttempt).where(
                CaseAttempt.run_id == uuid.UUID(run_id),
                CaseAttempt.test_case_id == test_case_id,
            )
        )
        if run is None or case is None or attempt is None:
            return
        now = _now()
        run.heartbeat_at = now
        attempt.heartbeat_at = now
        existing = session.scalar(
            select(CaseResult).where(
                CaseResult.run_id == run.id,
                CaseResult.test_case_id == case.id,
            )
        )
        if existing is not None:
            attempt.status = (
                "execution_error" if existing.execution_status == "execution_error" else "succeeded"
            )
            attempt.error_category = existing.error_category
            return
        target = session.get(TargetConfig, run.target_config_id)
        evaluation_case = _to_case(case)
        adapter_type = target.adapter_type if target is not None else "unknown"
        try:
            if adapter_type != "mock":
                outcome = asyncio.run(_execute_case(evaluation_case, _UnsupportedAdapter(), _evaluators(run)))
            else:
                outcome = asyncio.run(
                    _execute_case(evaluation_case, _mock_for(evaluation_case), _evaluators(run))
                )
            persist_case(session, run.id, case.id, outcome)
        except IntegrityError:
            session.rollback()
            return
        attempt.status = "execution_error" if outcome.execution_status == "execution_error" else "succeeded"
        attempt.error_category = outcome.error_category
        _write_progress(session, run, _case_count(session, run.dataset_version_id))


def _finalize(run_id: str) -> bool:
    with session_scope() as session:
        run = session.get(EvaluationRun, uuid.UUID(run_id))
        if run is None or run.status in {"completed", "partial"}:
            return True
        total = _case_count(session, run.dataset_version_id)
        unresolved = _unresolved(session, run.id, total)
        execution_errors = int(
            session.scalar(
                select(func.count())
                .select_from(CaseResult)
                .where(CaseResult.run_id == run.id, CaseResult.execution_status == "execution_error")
            )
            or 0
        )
        decided = completion_status(run.status, unresolved, execution_errors)
        if decided is None:
            return False
        summary = _summary(session, run.id, total, execution_errors)
        if run.status == "running":
            event = "partial" if decided == "partial" else "succeed"
            run.status = transition(run.status, event)
        run.summary = summary
        run.progress = summary
        run.finished_at = _now()
        run.heartbeat_at = run.finished_at
        return True


def _summary(session, run_id: uuid.UUID, total: int, execution_errors: int) -> dict:
    def _category(name: str) -> int:
        return int(
            session.scalar(
                select(func.count())
                .select_from(CaseResult)
                .where(CaseResult.run_id == run_id, CaseResult.error_category == name)
            )
            or 0
        )

    quality_fail_count = int(
        session.scalar(
            select(func.count())
            .select_from(MetricResult)
            .where(MetricResult.run_id == run_id, MetricResult.status == "failed")
        )
        or 0
    )
    return {
        "case_count": total,
        "execution_errors": execution_errors,
        "timeout_count": _category("timeout"),
        "rate_limit_count": _category("rate_limit"),
        "provider_error_count": _category("provider_error"),
        "quality_fail_count": quality_fail_count,
    }


def _write_progress(session, run: EvaluationRun, total: int) -> None:
    resolved = int(
        session.scalar(
            select(func.count())
            .select_from(CaseAttempt)
            .where(CaseAttempt.run_id == run.id, CaseAttempt.status != "claimed")
        )
        or 0
    )
    run.progress = {"total": total, "resolved": resolved}


def _case_count(session, version_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(TestCase).where(TestCase.dataset_version_id == version_id)
        )
        or 0
    )


def _unresolved(session, run_id: uuid.UUID, total: int) -> int:
    terminal = int(
        session.scalar(
            select(func.count())
            .select_from(CaseAttempt)
            .where(CaseAttempt.run_id == run_id, CaseAttempt.status != "claimed")
        )
        or 0
    )
    return total - terminal


def _is_cancelled(run_id: str) -> bool:
    with session_scope() as session:
        run = session.get(EvaluationRun, uuid.UUID(run_id))
        return run is not None and run.status == "cancelled"


def _release_claims(run_id: str, test_case_ids: list[uuid.UUID]) -> None:
    if not test_case_ids:
        return
    with session_scope() as session:
        attempts = session.scalars(
            select(CaseAttempt).where(
                CaseAttempt.run_id == uuid.UUID(run_id),
                CaseAttempt.test_case_id.in_(test_case_ids),
                CaseAttempt.status == "claimed",
            )
        ).all()
        for attempt in attempts:
            existing = session.scalar(
                select(CaseResult.id).where(
                    CaseResult.run_id == attempt.run_id,
                    CaseResult.test_case_id == attempt.test_case_id,
                )
            )
            if existing is None:
                session.delete(attempt)


def _evaluators(run: EvaluationRun) -> list:
    names = [item["name"] for item in run.snapshot.get("evaluators", [])]
    return [_REGISTRY[name]() for name in names if name in _REGISTRY]


def _to_case(row: TestCase) -> EvaluationCase:
    return EvaluationCase(
        case_key=row.case_key,
        input_text=row.input_text,
        expected_output=row.expected_output,
        context=row.context,
        tags=tuple(row.tags or []),
        json_schema=row.json_schema,
    )


def _mock_for(case: EvaluationCase) -> MockTargetAdapter:
    if case.case_key == "case-timeout":
        script = timeout_result()
    elif case.case_key == "case-rate-limit":
        script = rate_limit_result()
    elif case.case_key == "case-wrong":
        script = success_result("wrong answer")
    else:
        script = success_result(case.expected_output)
    return MockTargetAdapter({case.case_key: script})


class _UnsupportedAdapter:
    async def invoke(self, input_text: str, metadata: dict) -> TargetResult:
        return TargetResult(
            output="",
            context=[],
            metadata={},
            error_category="provider_error",
            error_detail=f"Adapter is not supported in this version",
        )

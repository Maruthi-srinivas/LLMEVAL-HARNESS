"""Release expired claims and republish runs whose worker disappeared."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from backend.app.db import session_scope
from backend.app.models import CaseAttempt, CaseResult, EvaluationRun

DEFAULT_STALE_SECONDS = 15


def recover_runs(stale_after_seconds: float = DEFAULT_STALE_SECONDS) -> list[str]:
    """Delete stale claims that have no result and republish runs that need a worker."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    published: list[str] = []
    with session_scope() as session:
        stale_attempts = session.scalars(
            select(CaseAttempt).where(
                CaseAttempt.status == "claimed",
                CaseAttempt.heartbeat_at < cutoff,
            )
        ).all()
        for attempt in stale_attempts:
            existing = session.scalar(
                select(CaseResult.id).where(
                    CaseResult.run_id == attempt.run_id,
                    CaseResult.test_case_id == attempt.test_case_id,
                )
            )
            if existing is None:
                session.delete(attempt)
        runs = session.scalars(
            select(EvaluationRun).where(
                or_(
                    (
                        (EvaluationRun.status == "queued")
                        & (EvaluationRun.created_at <= cutoff)
                        & (
                            EvaluationRun.heartbeat_at.is_(None)
                            | (EvaluationRun.heartbeat_at < cutoff)
                        )
                    ),
                    (
                        (EvaluationRun.status == "running")
                        & (
                            EvaluationRun.heartbeat_at.is_(None)
                            | (EvaluationRun.heartbeat_at < cutoff)
                        )
                    ),
                )
            )
        ).all()
        published = [str(run.id) for run in runs]
    for run_id in published:
        from worker.tasks import send_process_run

        send_process_run(run_id)
    return published

"""Release expired claims and republish runs whose worker disappeared."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import or_, select

from backend.app.db import session_scope
from backend.app.models import CaseAttempt, CaseResult, EvaluationRun, OutboxEvent
from backend.app.settings import enqueue_runs_enabled
from worker.kafka_bus import consume_once, publish_event

DEFAULT_STALE_SECONDS = 15


def recover_runs(stale_after_seconds: float = DEFAULT_STALE_SECONDS) -> list[str]:
    """Delete stale claims and publish outbox rows that the broker never received."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    published: list[str] = []
    pending: list[tuple[str, str, dict]] = []
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
        pending = _unpublished(session, cutoff, force=False)
    _dispatch(pending)
    for run_id in published:
        from worker.tasks import send_process_run

        send_process_run(run_id)
    consume_once()
    return published


def drain_outbox(force: bool = False, stale_after_seconds: float = DEFAULT_STALE_SECONDS) -> list[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    with session_scope() as session:
        pending = _unpublished(session, cutoff, force=force)
    return _dispatch(pending)


def _unpublished(session, cutoff: datetime, force: bool) -> list[tuple[str, str, dict]]:
    rows = session.scalars(select(OutboxEvent).where(OutboxEvent.published_at.is_(None))).all()
    fresh_allowed = enqueue_runs_enabled()
    pending = []
    for row in rows:
        created = row.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        stale = created is None or created <= cutoff
        if force or fresh_allowed or stale:
            pending.append((str(row.id), str(row.run_id), dict(row.payload or {})))
    return pending


def _dispatch(pending: list[tuple[str, str, dict]]) -> list[str]:
    from worker.tasks import send_process_run

    sent = []
    for event_id, run_id, payload in pending:
        send_process_run(run_id)
        if publish_event(payload):
            _mark_published(event_id)
            sent.append(run_id)
    return sent


def _mark_published(event_id: str) -> None:
    with session_scope() as session:
        row = session.get(OutboxEvent, uuid.UUID(event_id))
        if row is not None:
            row.published_at = datetime.now(timezone.utc)

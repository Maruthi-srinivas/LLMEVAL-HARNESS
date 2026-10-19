"""Delete finished runs that are older than the workspace retention period."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from backend.app.models import (
    AuditEvent,
    CaseAttempt,
    CaseResult,
    EvaluationRun,
    Experiment,
    MetricResult,
    OutboxEvent,
    Project,
    ReviewRequest,
    Workspace,
)
from backend.app.services.artifacts import delete_report


def purge_expired(session: Session, now: datetime | None = None) -> int:
    moment = now or datetime.now(timezone.utc)
    removed = 0
    workspaces = session.scalars(select(Workspace).where(Workspace.retention_days.is_not(None))).all()
    for workspace in workspaces:
        cutoff = moment - timedelta(days=workspace.retention_days or 0)
        runs = session.scalars(
            select(EvaluationRun)
            .join(Project, EvaluationRun.project_id == Project.id)
            .where(
                Project.workspace_id == workspace.id,
                EvaluationRun.finished_at.is_not(None),
                EvaluationRun.finished_at < cutoff,
            )
        ).all()
        for run in runs:
            _delete_run(session, workspace, run)
            removed += 1
    return removed


def _delete_run(session: Session, workspace: Workspace, run: EvaluationRun) -> None:
    result_ids = list(session.scalars(select(CaseResult.id).where(CaseResult.run_id == run.id)).all())
    if result_ids:
        session.execute(delete(ReviewRequest).where(ReviewRequest.case_result_id.in_(result_ids)))
    session.execute(delete(MetricResult).where(MetricResult.run_id == run.id))
    session.execute(delete(CaseResult).where(CaseResult.run_id == run.id))
    session.execute(delete(CaseAttempt).where(CaseAttempt.run_id == run.id))
    session.execute(delete(OutboxEvent).where(OutboxEvent.run_id == run.id))
    session.execute(
        delete(Experiment).where(or_(Experiment.baseline_run_id == run.id, Experiment.candidate_run_id == run.id))
    )
    delete_report(workspace.id, run.id)
    session.delete(run)
    session.add(
        AuditEvent(
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            actor_id=None,
            action="deletion",
            resource_type="evaluation_run",
            resource_id=str(run.id),
        )
    )
    session.flush()

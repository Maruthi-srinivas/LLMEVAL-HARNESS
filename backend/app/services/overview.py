"""Workspace overview. Missing measurements stay null."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import Session

from backend.app.models import CaseResult, EvaluationRun, MetricResult, Project
from backend.app.services.experiments import recent_comparisons

_STATUSES = ("pending", "queued", "running", "completed", "partial", "cancelled")
_EXCLUDED_AVERAGES = ("safety", "tool_selection", "tool_arguments", "tool_permission", "tool_recovery", "tool_unnecessary")


def workspace_overview(
    session: Session,
    workspace_id: uuid.UUID,
    workspace_name: str,
    organization_name: str = "",
) -> dict:
    status_rows = session.execute(
        select(EvaluationRun.status, func.count())
        .join(Project, EvaluationRun.project_id == Project.id)
        .where(Project.workspace_id == workspace_id)
        .group_by(EvaluationRun.status)
    ).all()
    counts = {status: 0 for status in _STATUSES}
    for status, count in status_rows:
        counts[status] = int(count)

    metric_rows = session.execute(
        select(MetricResult.metric_name, func.avg(MetricResult.score))
        .join(EvaluationRun, MetricResult.run_id == EvaluationRun.id)
        .join(Project, EvaluationRun.project_id == Project.id)
        .where(
            Project.workspace_id == workspace_id,
            MetricResult.score.is_not(None),
            MetricResult.metric_name.notin_(_EXCLUDED_AVERAGES),
        )
        .group_by(MetricResult.metric_name)
        .order_by(MetricResult.metric_name)
    ).all()
    metric_averages = (
        [{"metric_name": name, "average": float(average)} for name, average in metric_rows] if metric_rows else None
    )

    latency = session.execute(
        select(
            func.percentile_cont(0.5).within_group(CaseResult.latency_ms),
            func.percentile_cont(0.95).within_group(CaseResult.latency_ms),
        )
        .join(EvaluationRun, CaseResult.run_id == EvaluationRun.id)
        .join(Project, EvaluationRun.project_id == Project.id)
        .where(
            Project.workspace_id == workspace_id,
            CaseResult.execution_status == "succeeded",
            CaseResult.latency_ms.is_not(None),
        )
    ).one()
    median, p95 = latency
    input_tokens, output_tokens = session.execute(
        select(
            func.sum(cast(CaseResult.token_usage["input_tokens"].astext, Float)),
            func.sum(cast(CaseResult.token_usage["output_tokens"].astext, Float)),
        )
        .join(EvaluationRun, CaseResult.run_id == EvaluationRun.id)
        .join(Project, EvaluationRun.project_id == Project.id)
        .where(Project.workspace_id == workspace_id)
    ).one()
    comparisons, regressions = recent_comparisons(session, workspace_id)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "workspace_id": str(workspace_id),
            "workspace_name": workspace_name,
            "organization_name": organization_name,
        },
        "status_counts": counts,
        "metric_averages": metric_averages,
        "latency_ms_median": None if median is None else float(median),
        "latency_ms_p95": None if p95 is None else float(p95),
        "token_usage": _tokens(input_tokens, output_tokens),
        "estimated_cost": None,
        "estimated_cost_reason": "no price configured",
        "safety": _safety_counts(session, workspace_id),
        "regressions": regressions,
        "comparisons": comparisons,
        "later_note": "CI release decisions arrive in a later version.",
    }


def _safety_counts(session: Session, workspace_id: uuid.UUID) -> dict | None:
    rows = session.execute(
        select(MetricResult.status, func.count())
        .join(EvaluationRun, MetricResult.run_id == EvaluationRun.id)
        .join(Project, EvaluationRun.project_id == Project.id)
        .where(Project.workspace_id == workspace_id, MetricResult.metric_name == "safety")
        .group_by(MetricResult.status)
    ).all()
    if not rows:
        return None
    counts = {"passed": 0, "failed": 0, "metric_error": 0}
    for status, count in rows:
        if status in counts:
            counts[status] = int(count)
    return counts


def _tokens(input_tokens, output_tokens) -> dict | None:
    if input_tokens is None and output_tokens is None:
        return None
    return {
        "input_tokens": None if input_tokens is None else float(input_tokens),
        "output_tokens": None if output_tokens is None else float(output_tokens),
    }

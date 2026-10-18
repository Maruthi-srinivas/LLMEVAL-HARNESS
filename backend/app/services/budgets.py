"""Workspace token budgets. A null budget does not limit new runs."""

from __future__ import annotations

import uuid

from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import Session

from backend.app.models import CaseResult, EvaluationRun, Project, Workspace


def tokens_spent(session: Session, workspace_id: uuid.UUID) -> float:
    incoming, outgoing = session.execute(
        select(
            func.coalesce(func.sum(cast(CaseResult.token_usage["input_tokens"].astext, Float)), 0),
            func.coalesce(func.sum(cast(CaseResult.token_usage["output_tokens"].astext, Float)), 0),
        )
        .join(EvaluationRun, CaseResult.run_id == EvaluationRun.id)
        .join(Project, EvaluationRun.project_id == Project.id)
        .where(Project.workspace_id == workspace_id)
    ).one()
    return float(incoming or 0) + float(outgoing or 0)


def budget_exhausted(session: Session, workspace_id: uuid.UUID) -> bool:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None or workspace.token_budget is None:
        return False
    return tokens_spent(session, workspace_id) >= float(workspace.token_budget)

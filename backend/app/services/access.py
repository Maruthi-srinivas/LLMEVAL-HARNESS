"""Workspace membership lookups. Missing and foreign rows look the same."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import APIError
from backend.app.models import Dataset, DatasetVersion, EvaluationRun, Membership, Project, TargetConfig, User, Workspace


@dataclass
class Principal:
    user: User
    workspace: Workspace
    project: Project
    role: str
    service_account_id: uuid.UUID | None = None


def require_writer(principal: Principal) -> None:
    if principal.role not in {"owner", "member", "service"}:
        raise APIError(403, "forbidden", "This action requires a member")


def require_owner(principal: Principal) -> None:
    if principal.role != "owner":
        raise APIError(403, "forbidden", "This action requires the workspace owner")


def principal_for_user(session: Session, user: User, workspace_id: uuid.UUID | None = None) -> Principal:
    query = select(Membership).where(Membership.user_id == user.id)
    if workspace_id is None:
        membership = session.scalar(query.order_by(Membership.created_at.asc()))
        if membership is None:
            raise APIError(401, "unauthorized", "Authentication required")
    else:
        membership = session.scalar(query.where(Membership.workspace_id == workspace_id))
        if membership is None:
            raise APIError(404, "validation_error", "Resource not found")
    return _principal(session, user, membership.workspace_id, membership.role, None)


def _principal(
    session: Session,
    user: User,
    workspace_id: uuid.UUID,
    role: str,
    service_account_id: uuid.UUID | None,
) -> Principal:
    workspace = session.get(Workspace, workspace_id)
    project = session.scalar(select(Project).where(Project.workspace_id == workspace_id, Project.name == "default"))
    if workspace is None or project is None:
        raise APIError(401, "unauthorized", "Authentication required")
    return Principal(
        user=user,
        workspace=workspace,
        project=project,
        role=role,
        service_account_id=service_account_id,
    )


def require_project(session: Session, workspace_id: uuid.UUID, project_id: uuid.UUID, code: str) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise APIError(404, code, "Resource not found")
    return project


def require_dataset(session: Session, workspace_id: uuid.UUID, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.scalar(
        select(Dataset)
        .join(Project, Dataset.project_id == Project.id)
        .where(Dataset.id == dataset_id, Project.workspace_id == workspace_id)
    )
    if dataset is None:
        raise APIError(404, "invalid_dataset", "Resource not found")
    return dataset


def require_dataset_version(
    session: Session, workspace_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[Dataset, DatasetVersion]:
    row = session.execute(
        select(Dataset, DatasetVersion)
        .join(DatasetVersion, DatasetVersion.dataset_id == Dataset.id)
        .join(Project, Dataset.project_id == Project.id)
        .where(DatasetVersion.id == version_id, Project.workspace_id == workspace_id)
    ).first()
    if row is None:
        raise APIError(404, "invalid_dataset", "Resource not found")
    return row[0], row[1]


def require_target(session: Session, workspace_id: uuid.UUID, target_id: uuid.UUID) -> TargetConfig:
    target = session.scalar(
        select(TargetConfig)
        .join(Project, TargetConfig.project_id == Project.id)
        .where(TargetConfig.id == target_id, Project.workspace_id == workspace_id)
    )
    if target is None:
        raise APIError(404, "validation_error", "Resource not found")
    return target


def require_run(session: Session, workspace_id: uuid.UUID, run_id: uuid.UUID) -> EvaluationRun:
    run = session.scalar(
        select(EvaluationRun)
        .join(Project, EvaluationRun.project_id == Project.id)
        .where(EvaluationRun.id == run_id, Project.workspace_id == workspace_id)
    )
    if run is None:
        raise APIError(404, "unknown_run", "Resource not found")
    return run

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


def principal_for_user(session: Session, user: User) -> Principal:
    membership = session.scalar(select(Membership).where(Membership.user_id == user.id))
    if membership is None:
        raise APIError(401, "unauthorized", "Authentication required")
    workspace = session.get(Workspace, membership.workspace_id)
    project = session.scalar(
        select(Project).where(Project.workspace_id == membership.workspace_id, Project.name == "default")
    )
    if workspace is None or project is None:
        raise APIError(401, "unauthorized", "Authentication required")
    return Principal(user=user, workspace=workspace, project=project, role=membership.role)


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

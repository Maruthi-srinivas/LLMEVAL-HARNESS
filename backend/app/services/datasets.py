"""Dataset import and reads."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import Dataset, DatasetVersion, Project, TestCase
from backend.app.settings import MAX_DATASET_CASES
from evaluator.datasets.loader import content_hash
from evaluator.types import EvaluationCase


def import_cases(
    session: Session,
    project: Project,
    dataset_name: str,
    cases: list[EvaluationCase],
) -> tuple[Dataset, DatasetVersion, int]:
    if len(cases) > MAX_DATASET_CASES:
        from backend.app.errors import APIError

        raise APIError(400, "invalid_dataset", f"Dataset exceeds {MAX_DATASET_CASES} cases")

    dataset = session.scalar(
        select(Dataset).where(Dataset.project_id == project.id, Dataset.name == dataset_name)
    )
    if dataset is None:
        dataset = Dataset(project_id=project.id, name=dataset_name)
        session.add(dataset)
        session.flush()

    digest = content_hash(cases)
    existing = session.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset.id,
            DatasetVersion.content_hash == digest,
        )
    )
    if existing is not None:
        count = session.scalar(
            select(func.count()).select_from(TestCase).where(TestCase.dataset_version_id == existing.id)
        )
        return dataset, existing, int(count or 0)

    current_max = session.scalar(
        select(func.max(DatasetVersion.version_number)).where(DatasetVersion.dataset_id == dataset.id)
    )
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=(current_max or 0) + 1,
        content_hash=digest,
    )
    session.add(version)
    session.flush()
    for case in cases:
        session.add(
            TestCase(
                dataset_version_id=version.id,
                case_key=case.case_key,
                input_text=case.input_text,
                expected_output=case.expected_output,
                context=case.context,
                tags=list(case.tags),
                json_schema=case.json_schema,
                relevant_document_ids=list(case.relevant_document_ids),
                retrieved_context=None if case.retrieved_context is None else list(case.retrieved_context),
                citations=list(case.citations),
                expected_policy=case.expected_policy,
                human_labels=case.human_labels,
                allowed_tools=list(case.allowed_tools),
                goal=case.goal,
                constraints=list(case.constraints),
                expected_tools=list(case.expected_tools),
            )
        )
    session.flush()
    return dataset, version, len(cases)


def list_datasets(session: Session, workspace_id: uuid.UUID) -> list[dict]:
    rows = session.execute(
        select(Dataset, func.count(DatasetVersion.id))
        .join(Project, Dataset.project_id == Project.id)
        .outerjoin(DatasetVersion, DatasetVersion.dataset_id == Dataset.id)
        .where(Project.workspace_id == workspace_id)
        .group_by(Dataset.id)
        .order_by(Dataset.name)
    ).all()
    return [
        {
            "id": str(dataset.id),
            "name": dataset.name,
            "project_id": str(dataset.project_id),
            "version_count": int(version_count),
            "created_at": dataset.created_at.isoformat(),
        }
        for dataset, version_count in rows
    ]


def version_summaries(session: Session, dataset_id: uuid.UUID) -> list[dict]:
    versions = session.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version_number)
    ).all()
    summaries = []
    for version in versions:
        count = session.scalar(
            select(func.count()).select_from(TestCase).where(TestCase.dataset_version_id == version.id)
        )
        summaries.append(
            {
                "id": str(version.id),
                "version_number": version.version_number,
                "content_hash": version.content_hash,
                "case_count": int(count or 0),
            }
        )
    return summaries


def cases_for_version(session: Session, version_id: uuid.UUID) -> list[TestCase]:
    return list(
        session.scalars(
            select(TestCase).where(TestCase.dataset_version_id == version_id).order_by(TestCase.case_key)
        ).all()
    )

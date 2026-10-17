"""Persist a sample run. Dataset versions are inserted once and never updated."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import (
    CaseResult,
    Dataset,
    DatasetVersion,
    EvaluationRun,
    EvaluatorConfig,
    MetricResult,
    Project,
    TargetConfig,
    TestCase,
    Workspace,
)
from evaluator.datasets.loader import content_hash
from evaluator.metrics.deterministic import Evaluator
from evaluator.status import transition
from evaluator.types import CaseExecution, EvaluationCase

DEMO_WORKSPACE = "demo"
DEMO_PROJECT = "support-assistant"
DEMO_DATASET = "support-qa"
DEMO_TARGET = "sample-mock"


def _get_or_create(session: Session, model, filters: dict, values: dict):
    statement = select(model)
    for key, value in filters.items():
        statement = statement.where(getattr(model, key) == value)
    existing = session.scalar(statement)
    if existing is not None:
        return existing
    row = model(**filters, **values)
    session.add(row)
    session.flush()
    return row


def ensure_demo_graph(session: Session, evaluators: list[Evaluator]) -> tuple[Project, TargetConfig]:
    workspace = _get_or_create(session, Workspace, {"name": DEMO_WORKSPACE}, {})
    project = _get_or_create(
        session,
        Project,
        {"workspace_id": workspace.id, "name": DEMO_PROJECT},
        {},
    )
    target = _get_or_create(
        session,
        TargetConfig,
        {"project_id": project.id, "name": DEMO_TARGET},
        {"adapter_type": "mock", "config": {}},
    )
    for evaluator in evaluators:
        _get_or_create(
            session,
            EvaluatorConfig,
            {"project_id": project.id, "name": evaluator.name},
            {"version": evaluator.version, "config": {}},
        )
    return project, target


def ensure_dataset_version(session: Session, project_id: uuid.UUID, cases: list[EvaluationCase]) -> DatasetVersion:
    dataset = _get_or_create(
        session,
        Dataset,
        {"project_id": project_id, "name": DEMO_DATASET},
        {},
    )
    digest = content_hash(cases)
    existing = session.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset.id,
            DatasetVersion.content_hash == digest,
        )
    )
    if existing is not None:
        return existing

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
            )
        )
    session.flush()
    return version


def create_run(
    session: Session,
    project: Project,
    version: DatasetVersion,
    target: TargetConfig,
    evaluators: list[Evaluator],
) -> EvaluationRun:
    run = EvaluationRun(
        project_id=project.id,
        dataset_version_id=version.id,
        target_config_id=target.id,
        status="pending",
        snapshot={
            "dataset_name": DEMO_DATASET,
            "dataset_version": version.version_number,
            "dataset_content_hash": version.content_hash,
            "target_name": target.name,
            "target_adapter": target.adapter_type,
            "prompt_hash": None,
            "evaluators": [{"name": item.name, "version": item.version} for item in evaluators],
        },
    )
    session.add(run)
    session.flush()
    return run


def mark_running(session: Session, run: EvaluationRun) -> None:
    run.status = transition(run.status, "start")
    run.started_at = datetime.now(timezone.utc)
    session.flush()


def case_ids_by_key(session: Session, version_id: uuid.UUID) -> dict[str, uuid.UUID]:
    rows = session.scalars(select(TestCase).where(TestCase.dataset_version_id == version_id))
    return {row.case_key: row.id for row in rows}


def persist_case(
    session: Session,
    run_id: uuid.UUID,
    test_case_id: uuid.UUID,
    result: CaseExecution,
) -> None:
    if result.execution_status == "execution_error" and result.scores:
        raise RuntimeError("Execution errors must not store quality scores")
    case_result = CaseResult(
        run_id=run_id,
        test_case_id=test_case_id,
        execution_status=result.execution_status,
        output=result.output,
        error_category=result.error_category,
        error_detail=result.error_detail,
        latency_ms=result.latency_ms,
        token_usage=result.token_usage,
        result_metadata={},
    )
    session.add(case_result)
    session.flush()
    for score in result.scores:
        if score.status == "skipped":
            continue
        session.add(
            MetricResult(
                run_id=run_id,
                case_result_id=case_result.id,
                metric_name=score.metric_name,
                status=score.status,
                score=score.score,
                explanation=score.explanation,
                details=score.metadata,
            )
        )
    session.flush()


def finalize_run(session: Session, run: EvaluationRun, status: str, summary: dict) -> None:
    event = "partial" if status == "partial" else "succeed"
    run.status = transition(run.status, event)
    run.summary = summary
    run.finished_at = datetime.now(timezone.utc)
    session.flush()

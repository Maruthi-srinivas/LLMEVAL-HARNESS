"""Queued evaluation runs. This module does not call a target adapter."""

from __future__ import annotations

import uuid
from copy import deepcopy

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.errors import APIError
from backend.app.models import (
    CaseResult,
    DatasetVersion,
    EvaluationRun,
    EvaluatorConfig,
    MetricResult,
    Project,
    TargetConfig,
    TestCase,
)
from backend.app.settings import MAX_QUEUED_RUNS
from evaluator.metrics.deterministic import (
    ErrorRateEvaluator,
    ExactMatchEvaluator,
    JsonSchemaEvaluator,
    LatencyEvaluator,
    NormalizedMatchEvaluator,
    TokenF1Evaluator,
    TokenUsageEvaluator,
)
from evaluator.runner import IncompatibleConfiguration, validate_configuration
from evaluator.types import EvaluationCase

_REGISTRY = {
    item.name: item
    for item in (
        ExactMatchEvaluator,
        NormalizedMatchEvaluator,
        TokenF1Evaluator,
        JsonSchemaEvaluator,
        LatencyEvaluator,
        TokenUsageEvaluator,
        ErrorRateEvaluator,
    )
}


def _cases(session: Session, version_id: uuid.UUID) -> list[EvaluationCase]:
    rows = session.scalars(select(TestCase).where(TestCase.dataset_version_id == version_id)).all()
    return [
        EvaluationCase(
            case_key=row.case_key,
            input_text=row.input_text,
            expected_output=row.expected_output,
            context=row.context,
            tags=tuple(row.tags or []),
            json_schema=row.json_schema,
        )
        for row in rows
    ]


def queued_run_count(session: Session, workspace_id: uuid.UUID) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(EvaluationRun)
        .join(Project, EvaluationRun.project_id == Project.id)
        .where(Project.workspace_id == workspace_id, EvaluationRun.status == "queued")
    )
    return int(count or 0)


def create_queued_run(
    session: Session,
    version: DatasetVersion,
    target: TargetConfig,
    evaluator_names: list[str],
) -> EvaluationRun:
    if queued_run_count(session, _workspace_id(session, target.project_id)) >= MAX_QUEUED_RUNS:
        raise APIError(409, "quota_exceeded", f"Workspace already has {MAX_QUEUED_RUNS} queued runs")

    resolved = []
    for name in evaluator_names:
        evaluator_type = _REGISTRY.get(name)
        if evaluator_type is None:
            raise APIError(400, "unsupported_evaluator", f"Unknown evaluator {name}")
        instance = evaluator_type()
        stored = session.scalar(
            select(EvaluatorConfig).where(
                EvaluatorConfig.project_id == target.project_id,
                EvaluatorConfig.name == name,
            )
        )
        resolved.append(
            {
                "instance": instance,
                "name": instance.name,
                "version": stored.version if stored is not None else instance.version,
                "config": deepcopy(stored.config) if stored is not None else {},
            }
        )
    try:
        validate_configuration(_cases(session, version.id), [item["instance"] for item in resolved])
    except IncompatibleConfiguration as exc:
        raise APIError(400, "unsupported_evaluator", str(exc)) from exc

    prompt_version = None
    if isinstance(target.config, dict):
        prompt_version = target.config.get("prompt_version")
    snapshot = {
        "dataset_id": str(version.dataset_id),
        "dataset_version": version.version_number,
        "dataset_content_hash": version.content_hash,
        "target_name": target.name,
        "target_adapter": target.adapter_type,
        "target_config": deepcopy(target.config),
        "prompt_version": prompt_version,
        "evaluators": [
            {"name": item["name"], "version": item["version"], "config": item["config"]} for item in resolved
        ],
    }
    run = EvaluationRun(
        project_id=version_project_id(session, version),
        dataset_version_id=version.id,
        target_config_id=target.id,
        status="queued",
        snapshot=snapshot,
    )
    session.add(run)
    session.flush()
    return run


def version_project_id(session: Session, version: DatasetVersion) -> uuid.UUID:
    from backend.app.models import Dataset

    dataset = session.get(Dataset, version.dataset_id)
    if dataset is None:
        raise APIError(404, "invalid_dataset", "Resource not found")
    return dataset.project_id


def _workspace_id(session: Session, project_id: uuid.UUID) -> uuid.UUID:
    project = session.get(Project, project_id)
    if project is None:
        raise APIError(404, "validation_error", "Resource not found")
    return project.workspace_id


def case_results(session: Session, run_id: uuid.UUID) -> list[dict]:
    rows = session.execute(
        select(TestCase.case_key, CaseResult)
        .join(TestCase, CaseResult.test_case_id == TestCase.id)
        .where(CaseResult.run_id == run_id)
        .order_by(TestCase.case_key)
    ).all()
    payload = []
    for case_key, result in rows:
        metrics = session.scalars(
            select(MetricResult).where(MetricResult.case_result_id == result.id).order_by(MetricResult.metric_name)
        ).all()
        payload.append(
            {
                "case_key": case_key,
                "execution_status": result.execution_status,
                "output": result.output,
                "error_category": result.error_category,
                "error_detail": result.error_detail,
                "metrics": [
                    {
                        "metric_name": metric.metric_name,
                        "status": metric.status,
                        "score": metric.score,
                        "explanation": metric.explanation,
                    }
                    for metric in metrics
                ],
            }
        )
    return payload

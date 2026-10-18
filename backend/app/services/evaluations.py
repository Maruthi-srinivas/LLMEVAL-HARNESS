"""Queued evaluation runs. This module does not call a target adapter."""

from __future__ import annotations

import uuid
from copy import deepcopy

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.errors import APIError
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
)
from backend.app.settings import MAX_QUEUED_RUNS
from backend.app.services.budgets import budget_exhausted
from evaluator.metrics.deterministic import (
    ErrorRateEvaluator,
    ExactMatchEvaluator,
    JsonSchemaEvaluator,
    LatencyEvaluator,
    NormalizedMatchEvaluator,
    TokenF1Evaluator,
    TokenUsageEvaluator,
)
from evaluator.metrics.agent import (
    ToolArgumentsEvaluator,
    ToolPermissionEvaluator,
    ToolRecoveryEvaluator,
    ToolSelectionEvaluator,
    ToolUnnecessaryEvaluator,
)
from evaluator.metrics.rag import (
    AnswerRelevanceEvaluator,
    CitationCorrectnessEvaluator,
    CorrectnessEvaluator,
    FaithfulnessEvaluator,
    PrecisionAt5Evaluator,
    RecallAt5Evaluator,
    TaskCompletionEvaluator,
)
from evaluator.metrics.safety import SafetyEvaluator, StructuredOutputEvaluator
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
        RecallAt5Evaluator,
        PrecisionAt5Evaluator,
        CitationCorrectnessEvaluator,
        CorrectnessEvaluator,
        AnswerRelevanceEvaluator,
        FaithfulnessEvaluator,
        SafetyEvaluator,
        StructuredOutputEvaluator,
        ToolSelectionEvaluator,
        ToolArgumentsEvaluator,
        ToolPermissionEvaluator,
        ToolRecoveryEvaluator,
        ToolUnnecessaryEvaluator,
        TaskCompletionEvaluator,
    )
}


def evaluator_contracts() -> list[dict]:
    contracts = []
    for evaluator_type in _REGISTRY.values():
        minimum, maximum = (None, None) if evaluator_type.score_range is None else evaluator_type.score_range
        contracts.append(
            {
                "name": evaluator_type.name,
                "version": evaluator_type.version,
                "required_inputs": sorted(evaluator_type.required_fields),
                "config_schema": evaluator_type.config_schema,
                "score_range": {"min": minimum, "max": maximum},
                "failure_behavior": evaluator_type.failure_behavior,
            }
        )
    return sorted(contracts, key=lambda item: item["name"])


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
            relevant_document_ids=tuple(row.relevant_document_ids or []),
            retrieved_context=None if row.retrieved_context is None else tuple(row.retrieved_context),
            citations=tuple(row.citations or []),
            expected_policy=row.expected_policy,
            human_labels=row.human_labels,
            allowed_tools=tuple(row.allowed_tools or []),
            goal=row.goal,
            constraints=tuple(row.constraints or []),
            expected_tools=tuple(row.expected_tools or []),
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
    workspace_id = _workspace_id(session, target.project_id)
    if budget_exhausted(session, workspace_id):
        raise APIError(409, "quota_exceeded", "Workspace token budget is spent")

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
        config = deepcopy(stored.config) if stored is not None else {}
        if not config and instance.name in {"correctness", "answer_relevance", "faithfulness"}:
            config = {"judge_model": "mock-judge", "rubric": instance.name, "rubric_version": instance.version}
        resolved.append(
            {
                "instance": instance,
                "name": instance.name,
                "version": stored.version if stored is not None else instance.version,
                "config": config,
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
    from backend.app.models import OutboxEvent

    session.add(
        OutboxEvent(
            run_id=run.id,
            event_name="evaluation.queued",
            event_version=1,
            payload={"event_id": str(run.id), "event_name": "evaluation.queued", "event_version": 1, "run_id": str(run.id)},
        )
    )
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


def list_runs(session: Session, workspace_id: uuid.UUID) -> list[dict]:
    rows = session.execute(
        select(EvaluationRun, Dataset.name)
        .join(Project, EvaluationRun.project_id == Project.id)
        .join(DatasetVersion, EvaluationRun.dataset_version_id == DatasetVersion.id)
        .join(Dataset, DatasetVersion.dataset_id == Dataset.id)
        .where(Project.workspace_id == workspace_id)
        .order_by(EvaluationRun.created_at.desc())
    ).all()
    listed = []
    for run, dataset_name in rows:
        snapshot = run.snapshot if isinstance(run.snapshot, dict) else {}
        listed.append(
            {
                "run_id": str(run.id),
                "status": run.status,
                "dataset_name": dataset_name,
                "dataset_version": snapshot.get("dataset_version"),
                "target_name": snapshot.get("target_name"),
                "created_at": run.created_at.isoformat(),
            }
        )
    return listed


def case_results(session: Session, run_id: uuid.UUID) -> list[dict]:
    rows = session.execute(
        select(TestCase, CaseResult)
        .join(TestCase, CaseResult.test_case_id == TestCase.id)
        .where(CaseResult.run_id == run_id)
        .order_by(TestCase.case_key)
    ).all()
    payload = []
    for case, result in rows:
        metrics = session.scalars(
            select(MetricResult).where(MetricResult.case_result_id == result.id).order_by(MetricResult.metric_name)
        ).all()
        payload.append(
            {
                "case_key": case.case_key,
                "input": case.input_text,
                "expected_output": case.expected_output,
                "tags": case.tags or [],
                "execution_status": result.execution_status,
                "output": result.output,
                "error_category": result.error_category,
                "error_detail": result.error_detail,
                "latency_ms": result.latency_ms,
                "token_usage": result.token_usage or {},
                "retrieved_documents": result.retrieved_documents,
                "citations": result.citations,
                "trace": result.trace,
                "case_result_id": str(result.id),
                "metrics": [
                    {
                        "metric_name": metric.metric_name,
                        "status": metric.status,
                        "score": metric.score,
                        "explanation": metric.explanation,
                        "details": metric.details or {},
                    }
                    for metric in metrics
                ],
            }
        )
    return payload

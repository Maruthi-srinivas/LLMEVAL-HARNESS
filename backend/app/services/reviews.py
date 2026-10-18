"""Human review of one case. Approval copies labels into a new dataset version."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import APIError
from backend.app.models import CaseResult, Dataset, DatasetVersion, Project, ReviewRequest, TestCase
from backend.app.services.access import Principal, require_run
from backend.app.services.datasets import cases_for_version, import_cases
from evaluator.types import EvaluationCase

_LABELS = {"passed", "failed", "metric_error"}


def queue_review(
    session: Session,
    principal: Principal,
    run_id: uuid.UUID,
    case_key: str,
    labels: dict,
) -> dict:
    _check_labels(labels)
    run = require_run(session, principal.workspace.id, run_id)
    found = session.execute(
        select(CaseResult, TestCase)
        .join(TestCase, CaseResult.test_case_id == TestCase.id)
        .where(CaseResult.run_id == run.id, TestCase.case_key == case_key)
    ).one_or_none()
    if found is None:
        raise APIError(404, "unknown_run", "Resource not found")
    result, _case = found
    review = ReviewRequest(
        case_result_id=result.id,
        dataset_version_id=run.dataset_version_id,
        requested_labels=labels,
        status="pending",
        requested_by=principal.user.id,
    )
    session.add(review)
    session.flush()
    return _payload(review)


def approve_review(session: Session, principal: Principal, review_id: uuid.UUID) -> dict:
    review = _review_in_workspace(session, principal.workspace.id, review_id)
    if principal.role != "owner":
        raise APIError(403, "forbidden", "Only the workspace owner can approve a review")
    if review.status != "pending":
        raise APIError(409, "validation_error", "This review is already approved")
    version = session.get(DatasetVersion, review.dataset_version_id)
    dataset = session.get(Dataset, version.dataset_id)
    project = session.get(Project, dataset.project_id)
    reviewed = session.get(CaseResult, review.case_result_id)
    reviewed_case = session.get(TestCase, reviewed.test_case_id)
    copied = []
    for row in cases_for_version(session, version.id):
        labels = row.human_labels
        if row.case_key == reviewed_case.case_key:
            labels = {**(row.human_labels or {}), **review.requested_labels}
        copied.append(_case_from_row(row, labels))
    _dataset, new_version, _count = import_cases(session, project, dataset.name, copied)
    review.status = "approved"
    review.approved_by = principal.user.id
    session.flush()
    payload = _payload(review)
    payload["dataset_id"] = str(dataset.id)
    payload["version_id"] = str(new_version.id)
    payload["version_number"] = new_version.version_number
    return payload


def _review_in_workspace(session: Session, workspace_id: uuid.UUID, review_id: uuid.UUID) -> ReviewRequest:
    review = session.get(ReviewRequest, review_id)
    if review is None:
        raise APIError(404, "validation_error", "Resource not found")
    result = session.get(CaseResult, review.case_result_id)
    require_run(session, workspace_id, result.run_id)
    return review


def _check_labels(labels: dict) -> None:
    if not isinstance(labels, dict) or not labels:
        raise APIError(422, "validation_error", "Review labels are required")
    for key, value in labels.items():
        if not isinstance(key, str) or key == "" or value not in _LABELS:
            raise APIError(422, "validation_error", "Review labels must be passed, failed, or metric_error")


def _case_from_row(row: TestCase, labels: dict | None) -> EvaluationCase:
    return EvaluationCase(
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
        human_labels=labels,
        allowed_tools=tuple(row.allowed_tools or []),
        goal=row.goal,
        constraints=tuple(row.constraints or []),
        expected_tools=tuple(row.expected_tools or []),
    )


def _payload(review: ReviewRequest) -> dict:
    return {
        "id": str(review.id),
        "case_result_id": str(review.case_result_id),
        "dataset_version_id": str(review.dataset_version_id),
        "requested_labels": review.requested_labels,
        "status": review.status,
        "approved_by": None if review.approved_by is None else str(review.approved_by),
    }

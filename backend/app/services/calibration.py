"""Compare stored metric statuses with human labels. The report is not saved."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import APIError
from backend.app.models import CaseResult, DatasetVersion, EvaluationRun, MetricResult, TestCase

_TERMINAL = {"completed", "partial", "cancelled"}


def calibration_report(
    session: Session,
    dataset_id: uuid.UUID,
    run: EvaluationRun,
    evaluator_names: list[str],
) -> dict:
    version = session.get(DatasetVersion, run.dataset_version_id)
    if version is None or version.dataset_id != dataset_id:
        raise APIError(404, "invalid_dataset", "Resource not found")
    if run.status not in _TERMINAL:
        raise APIError(409, "validation_error", "Calibration is available after the run finishes")

    rows = session.execute(
        select(TestCase, CaseResult)
        .join(CaseResult, CaseResult.test_case_id == TestCase.id)
        .where(CaseResult.run_id == run.id, TestCase.dataset_version_id == version.id)
    ).all()
    compared = 0
    agreements = 0
    disagreements = []
    for case, result in rows:
        labels = case.human_labels or {}
        metrics = {
            metric.metric_name: metric.status
            for metric in session.scalars(select(MetricResult).where(MetricResult.case_result_id == result.id)).all()
        }
        for name in evaluator_names:
            if name not in labels:
                continue
            status = metrics.get(name)
            if status is None:
                continue
            compared += 1
            if status == labels[name]:
                agreements += 1
                continue
            disagreements.append(
                {
                    "case_id": str(case.id),
                    "case_key": case.case_key,
                    "metric": name,
                    "human_label": labels[name],
                    "evaluator_status": status,
                }
            )
    return {
        "run_id": str(run.id),
        "compared": compared,
        "agreements": agreements,
        "match_rate": None if compared == 0 else agreements / compared,
        "disagreements": disagreements,
    }

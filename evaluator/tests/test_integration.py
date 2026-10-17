import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.db import session_scope
from backend.app.models import CaseResult, EvaluationRun, MetricResult, TestCase, User
from evaluator.cli import run_sample


def test_sample_run_persists_execution_errors_separately_from_quality_failures():
    with session_scope() as session:
        users_before = session.scalar(select(func.count()).select_from(User))

    first = run_sample()
    second = run_sample()

    assert first.run_id != second.run_id
    assert first.dataset_version_id == second.dataset_version_id
    assert first.status == "partial"
    assert first.summary["execution_errors"] == 1
    assert first.summary["metric_fail_counts"]["exact_match"] >= 1

    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(User)) == users_before
        version_case_count = session.scalar(
            select(func.count()).select_from(TestCase).where(TestCase.dataset_version_id == first.dataset_version_id)
        )
        assert version_case_count == 5

        rows = session.execute(
            select(TestCase.case_key, CaseResult)
            .join(TestCase, CaseResult.test_case_id == TestCase.id)
            .where(CaseResult.run_id == first.run_id)
        ).all()
        by_key = {case_key: case_result for case_key, case_result in rows}
        assert by_key["qa-err"].execution_status == "execution_error"
        assert by_key["qa-err"].error_category == "timeout"
        assert by_key["qa-002"].execution_status == "succeeded"
        assert by_key["qa-001"].execution_status == "succeeded"

        def metric(case_result, name):
            return session.scalar(
                select(MetricResult).where(
                    MetricResult.case_result_id == case_result.id,
                    MetricResult.metric_name == name,
                )
            )

        assert metric(by_key["qa-err"], "exact_match") is None
        assert session.scalar(
            select(func.count()).select_from(MetricResult).where(MetricResult.case_result_id == by_key["qa-err"].id)
        ) == 0
        assert metric(by_key["qa-002"], "exact_match").status == "failed"
        assert metric(by_key["qa-002"], "normalized_match").status == "passed"
        assert metric(by_key["qa-001"], "exact_match").status == "passed"

        stored = session.get(EvaluationRun, first.run_id)
        assert stored.status == "partial"
        assert stored.snapshot["dataset_version"] == 1
        assert stored.summary["execution_errors"] == 1

        succeeded = metric(by_key["qa-001"], "exact_match")
        session.add(
            MetricResult(
                run_id=succeeded.run_id,
                case_result_id=succeeded.case_result_id,
                metric_name=succeeded.metric_name,
                status="passed",
                score=1.0,
                explanation="duplicate",
                details={},
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

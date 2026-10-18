"""Compare two finished runs and store the release decision."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.errors import APIError
from backend.app.models import (
    CaseResult,
    Experiment,
    MetricResult,
    Project,
    ReleasePolicy,
    TestCase,
)
from backend.app.services.access import require_project, require_run

_TERMINAL = {"completed", "partial"}
_WARNING = (
    "Dataset versions are not equivalent. "
    "The score delta is not an unqualified model improvement."
)


@dataclass
class _CaseView:
    execution_status: str
    latency_ms: float | None
    input_tokens: float
    output_tokens: float
    metrics: dict[str, tuple[str, float | None]] = field(default_factory=dict)


def create_policy(session: Session, workspace_id: uuid.UUID, body) -> ReleasePolicy:
    project = require_project(session, workspace_id, body.project_id, "validation_error")
    policy = ReleasePolicy(
        project_id=project.id,
        name=body.name,
        metric_minimums=dict(body.metric_minimums),
        max_error_rate=body.max_error_rate,
        latency_budget_ms=body.latency_budget_ms,
        safety_required=body.safety_required,
        price_per_1k_tokens=body.price_per_1k_tokens,
        max_cost_increase=body.max_cost_increase,
    )
    session.add(policy)
    try:
        session.flush()
    except IntegrityError as exc:
        raise APIError(400, "validation_error", "Policy name is already in use") from exc
    return policy


def list_policies(session: Session, workspace_id: uuid.UUID) -> list[dict]:
    rows = session.scalars(
        select(ReleasePolicy)
        .join(Project, ReleasePolicy.project_id == Project.id)
        .where(Project.workspace_id == workspace_id)
        .order_by(ReleasePolicy.created_at.desc())
    ).all()
    return [policy_payload(row) for row in rows]


def create_experiment(session: Session, workspace_id: uuid.UUID, body) -> Experiment:
    project = require_project(session, workspace_id, body.project_id, "validation_error")
    if body.baseline_run_id == body.candidate_run_id:
        raise APIError(400, "validation_error", "Baseline and candidate must be different runs")
    baseline = require_run(session, workspace_id, body.baseline_run_id)
    candidate = require_run(session, workspace_id, body.candidate_run_id)
    if baseline.project_id != project.id or candidate.project_id != project.id:
        raise APIError(404, "unknown_run", "Resource not found")
    if baseline.status not in _TERMINAL or candidate.status not in _TERMINAL:
        raise APIError(409, "validation_error", "Experiment comparison is available after both runs finish")
    policy = session.scalar(
        select(ReleasePolicy).where(ReleasePolicy.id == body.policy_id, ReleasePolicy.project_id == project.id)
    )
    if policy is None:
        raise APIError(404, "validation_error", "Resource not found")

    decision, comparison = _compare(session, baseline, candidate, policy)
    experiment = Experiment(
        project_id=project.id,
        name=body.name,
        baseline_run_id=baseline.id,
        candidate_run_id=candidate.id,
        policy_id=policy.id,
        decision=decision,
        comparison=comparison,
    )
    session.add(experiment)
    try:
        session.flush()
    except IntegrityError as exc:
        raise APIError(400, "validation_error", "Experiment name is already in use") from exc
    return experiment


def list_experiments(session: Session, workspace_id: uuid.UUID) -> list[dict]:
    rows = session.scalars(
        select(Experiment)
        .join(Project, Experiment.project_id == Project.id)
        .where(Project.workspace_id == workspace_id)
        .order_by(Experiment.created_at.desc())
    ).all()
    return [experiment_payload(row) for row in rows]


def read_experiment(session: Session, workspace_id: uuid.UUID, experiment_id: uuid.UUID) -> dict:
    row = session.scalar(
        select(Experiment)
        .join(Project, Experiment.project_id == Project.id)
        .where(Experiment.id == experiment_id, Project.workspace_id == workspace_id)
    )
    if row is None:
        raise APIError(404, "validation_error", "Resource not found")
    return experiment_payload(row)


def recent_comparisons(session: Session, workspace_id: uuid.UUID, limit: int = 10) -> tuple[list[dict], list[dict]]:
    rows = session.scalars(
        select(Experiment)
        .join(Project, Experiment.project_id == Project.id)
        .where(Project.workspace_id == workspace_id)
        .order_by(Experiment.created_at.desc())
        .limit(limit)
    ).all()
    comparisons = [
        {
            "experiment_id": str(row.id),
            "name": row.name,
            "decision": row.decision,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    regressions = []
    for row in rows:
        stored = row.comparison if isinstance(row.comparison, dict) else {}
        for item in stored.get("regressions") or []:
            if not isinstance(item, dict):
                continue
            regressions.append(
                {
                    "experiment_id": str(row.id),
                    "experiment_name": row.name,
                    "candidate_run_id": str(row.candidate_run_id),
                    "case_key": item.get("case_key"),
                    "metric": item.get("metric"),
                }
            )
            if len(regressions) >= limit:
                return comparisons, regressions
    return comparisons, regressions


def policy_payload(row: ReleasePolicy) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "name": row.name,
        "metric_minimums": row.metric_minimums or {},
        "max_error_rate": row.max_error_rate,
        "latency_budget_ms": row.latency_budget_ms,
        "safety_required": row.safety_required,
        "price_per_1k_tokens": row.price_per_1k_tokens,
        "max_cost_increase": row.max_cost_increase,
        "created_at": row.created_at.isoformat(),
    }


def experiment_payload(row: Experiment) -> dict:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id),
        "name": row.name,
        "baseline_run_id": str(row.baseline_run_id),
        "candidate_run_id": str(row.candidate_run_id),
        "policy_id": str(row.policy_id),
        "decision": row.decision,
        "comparison": row.comparison,
        "created_at": row.created_at.isoformat(),
    }


def _compare(session: Session, baseline, candidate, policy: ReleasePolicy) -> tuple[str, dict]:
    baseline_cases = _cases_for_run(session, baseline.id)
    candidate_cases = _cases_for_run(session, candidate.id)
    matched = sorted(set(baseline_cases) & set(candidate_cases))
    equivalent = baseline.dataset_version_id == candidate.dataset_version_id
    deltas = _metric_deltas(baseline_cases, candidate_cases, matched)
    regressions = _regressions(baseline_cases, candidate_cases, matched)
    latency = _latency_change(baseline_cases, candidate_cases, matched)
    tokens = _token_change(baseline_cases, candidate_cases, matched)
    cost = _cost_change(tokens, policy.price_per_1k_tokens)
    evaluator_differences = _evaluator_differences(baseline.snapshot, candidate.snapshot)
    fail_reasons, review_reasons = _gates(
        policy,
        candidate_cases,
        matched,
        deltas,
        latency["candidate_median"],
        cost["change"],
    )
    if not equivalent:
        review_reasons.append("dataset versions differ")
    if evaluator_differences:
        review_reasons.append("evaluator name, version, or config differs")
    if not matched:
        review_reasons.append("no matched cases")
    if fail_reasons:
        decision = "fail"
    elif review_reasons:
        decision = "review"
    else:
        decision = "pass"
    comparison = {
        "matched_count": len(matched),
        "unmatched_baseline_count": len(set(baseline_cases) - set(candidate_cases)),
        "unmatched_candidate_count": len(set(candidate_cases) - set(baseline_cases)),
        "dataset_versions_equivalent": equivalent,
        "warning": None if equivalent else _WARNING,
        "metric_deltas": deltas,
        "regressions": regressions,
        "latency_ms": latency,
        "tokens": tokens,
        "cost": cost,
        "evaluator_differences": evaluator_differences,
        "gate_reasons": fail_reasons,
        "review_reasons": review_reasons,
        "decision": decision,
    }
    return decision, comparison


def _cases_for_run(session: Session, run_id: uuid.UUID) -> dict[str, _CaseView]:
    rows = session.execute(
        select(TestCase.case_key, CaseResult, MetricResult)
        .join(CaseResult, CaseResult.test_case_id == TestCase.id)
        .outerjoin(MetricResult, MetricResult.case_result_id == CaseResult.id)
        .where(CaseResult.run_id == run_id)
    ).all()
    grouped: dict[str, _CaseView] = {}
    for case_key, result, metric in rows:
        view = grouped.get(case_key)
        if view is None:
            incoming, outgoing = _usage(result.token_usage or {})
            view = _CaseView(
                execution_status=result.execution_status,
                latency_ms=result.latency_ms,
                input_tokens=incoming,
                output_tokens=outgoing,
            )
            grouped[case_key] = view
        if metric is not None:
            view.metrics[metric.metric_name] = (metric.status, metric.score)
    return grouped


def _metric_deltas(baseline: dict[str, _CaseView], candidate: dict[str, _CaseView], matched: list[str]) -> list[dict]:
    names = set()
    for key in matched:
        names.update(baseline[key].metrics)
        names.update(candidate[key].metrics)
    deltas = []
    for name in sorted(names):
        base = _average(baseline, matched, name)
        cand = _average(candidate, matched, name)
        deltas.append(
            {
                "metric_name": name,
                "baseline_average": base,
                "candidate_average": cand,
                "delta": None if base is None or cand is None else cand - base,
            }
        )
    return deltas


def _average(cases: dict[str, _CaseView], matched: list[str], metric_name: str) -> float | None:
    scores = []
    for key in matched:
        found = cases[key].metrics.get(metric_name)
        if found is None or found[1] is None:
            continue
        scores.append(found[1])
    if not scores:
        return None
    return sum(scores) / len(scores)


def _regressions(baseline: dict[str, _CaseView], candidate: dict[str, _CaseView], matched: list[str]) -> list[dict]:
    found = []
    for key in matched:
        names = set(baseline[key].metrics) & set(candidate[key].metrics)
        for name in sorted(names):
            before = baseline[key].metrics[name][0]
            after = candidate[key].metrics[name][0]
            if before == "passed" and after == "failed":
                found.append(
                    {
                        "case_key": key,
                        "metric": name,
                        "baseline_status": before,
                        "candidate_status": after,
                    }
                )
    return found


def _latency_change(baseline: dict[str, _CaseView], candidate: dict[str, _CaseView], matched: list[str]) -> dict:
    base = _median([baseline[key].latency_ms for key in matched if baseline[key].latency_ms is not None])
    cand = _median([candidate[key].latency_ms for key in matched if candidate[key].latency_ms is not None])
    return {
        "baseline_median": base,
        "candidate_median": cand,
        "change": None if base is None or cand is None else cand - base,
    }


def _token_change(baseline: dict[str, _CaseView], candidate: dict[str, _CaseView], matched: list[str]) -> dict:
    def totals(cases: dict[str, _CaseView]) -> dict[str, float]:
        incoming = sum(cases[key].input_tokens for key in matched)
        outgoing = sum(cases[key].output_tokens for key in matched)
        return {"input_tokens": incoming, "output_tokens": outgoing}

    base = totals(baseline)
    cand = totals(candidate)
    return {
        "baseline": base,
        "candidate": cand,
        "change": {
            "input_tokens": cand["input_tokens"] - base["input_tokens"],
            "output_tokens": cand["output_tokens"] - base["output_tokens"],
        },
    }


def _cost_change(tokens: dict, price_per_1k: float) -> dict:
    def cost(side: dict) -> float:
        total = float(side["input_tokens"]) + float(side["output_tokens"])
        return total / 1000.0 * price_per_1k

    baseline = cost(tokens["baseline"])
    candidate = cost(tokens["candidate"])
    return {
        "baseline": baseline,
        "candidate": candidate,
        "change": candidate - baseline,
        "price_per_1k_tokens": price_per_1k,
    }


def _evaluator_differences(baseline_snapshot, candidate_snapshot) -> list[dict]:
    baseline = _evaluator_map(baseline_snapshot)
    candidate = _evaluator_map(candidate_snapshot)
    names = sorted(set(baseline) | set(candidate))
    differences = []
    for name in names:
        before = baseline.get(name)
        after = candidate.get(name)
        if before != after:
            differences.append({"name": name, "baseline": before, "candidate": after})
    return differences


def _evaluator_map(snapshot) -> dict[str, dict]:
    if not isinstance(snapshot, dict):
        return {}
    mapped = {}
    for item in snapshot.get("evaluators") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            mapped[item["name"]] = {"version": item.get("version"), "config": item.get("config") or {}}
    return mapped


def _gates(policy: ReleasePolicy, candidate: dict[str, _CaseView], matched: list[str], deltas, candidate_latency, cost_change) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    reviews: list[str] = []
    averages = {item["metric_name"]: item["candidate_average"] for item in deltas}
    for name, minimum in sorted((policy.metric_minimums or {}).items()):
        average = averages.get(name)
        if average is None:
            failures.append(f"{name} is missing")
        elif average < float(minimum):
            failures.append(f"{name} average is below the minimum")
    if matched:
        errors = sum(1 for key in matched if candidate[key].execution_status == "execution_error")
        if errors / len(matched) > policy.max_error_rate:
            failures.append("error rate is above the maximum")
    if candidate_latency is None:
        reviews.append("latency budget has no samples")
    elif candidate_latency > policy.latency_budget_ms:
        failures.append("median latency is above the budget")
    for key in matched:
        safety = candidate[key].metrics.get("safety")
        if safety is not None and safety[0] == "failed":
            failures.append("critical safety miss")
            break
    if cost_change > policy.max_cost_increase:
        failures.append("cost increase is above the maximum")
    return failures, reviews


def _usage(usage: dict) -> tuple[float, float]:
    def number(key: str) -> float:
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return 0.0

    return number("input_tokens"), number("output_tokens")


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2

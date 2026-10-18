"""Stored experiment comparisons and release decisions."""

import uuid
from pathlib import Path

from backend.app.db import session_scope
from backend.app.models import EvaluatorConfig
from evaluator.tests.test_api import JSONL, _register, _token, _upload, client
from worker.execution import process_run

BASELINE = Path("sample_datasets/release_baseline.jsonl").read_text(encoding="utf-8")
CANDIDATE = Path("sample_datasets/release_candidate.jsonl").read_text(encoding="utf-8")


def _target(auth: dict, project_id: str, name: str, behavior: str | None = None) -> str:
    config = {"model": "mock-v1"}
    if behavior:
        config["behavior"] = behavior
    response = client.post(
        "/api/v1/targets",
        headers=auth,
        json={
            "project_id": project_id,
            "name": name,
            "adapter_type": "mock",
            "config": config,
            "prompt_version": "prompt-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _run(auth: dict, version_id: str, target_id: str, evaluators: list[str]) -> dict:
    response = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={"dataset_version_id": version_id, "target_id": target_id, "evaluator_names": evaluators},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _policy(auth: dict, project_id: str, name: str, minimums: dict) -> str:
    response = client.post(
        "/api/v1/policies",
        headers=auth,
        json={
            "project_id": project_id,
            "name": name,
            "metric_minimums": minimums,
            "max_error_rate": 1,
            "latency_budget_ms": 1000,
            "safety_required": True,
            "price_per_1k_tokens": 2,
            "max_cost_increase": 1,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _experiment(auth: dict, project_id: str, name: str, policy_id: str, baseline_id: str, candidate_id: str):
    return client.post(
        "/api/v1/experiments",
        headers=auth,
        json={
            "project_id": project_id,
            "name": name,
            "policy_id": policy_id,
            "baseline_run_id": baseline_id,
            "candidate_run_id": candidate_id,
        },
    )


def test_release_candidate_fails_on_faithfulness_regression():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=BASELINE, name="release")
    second = _upload(auth, owner["project_id"], content=CANDIDATE, name="release")
    assert uploaded["version_id"] != second["version_id"]
    baseline = _run(
        auth,
        uploaded["version_id"],
        _target(auth, owner["project_id"], "baseline-target", "release_baseline"),
        ["correctness", "faithfulness"],
    )
    candidate = _run(
        auth,
        second["version_id"],
        _target(auth, owner["project_id"], "candidate-target", "release_candidate"),
        ["correctness", "faithfulness"],
    )
    process_run(baseline["run_id"])
    process_run(candidate["run_id"])
    policy_id = _policy(
        auth,
        owner["project_id"],
        "block-faithfulness",
        {"correctness": 0.5, "faithfulness": 0.5},
    )
    created = _experiment(auth, owner["project_id"], "release-check", policy_id, baseline["run_id"], candidate["run_id"])
    assert created.status_code == 201, created.text
    body = created.json()
    comparison = body["comparison"]
    assert body["decision"] == "fail"
    assert comparison["matched_count"] == 1
    assert comparison["warning"]
    assert "not an unqualified model improvement" in comparison["warning"]
    correctness = next(item for item in comparison["metric_deltas"] if item["metric_name"] == "correctness")
    assert correctness["delta"] > 0
    assert any(item["case_key"] == "release-main" and item["metric"] == "faithfulness" for item in comparison["regressions"])
    assert any("faithfulness" in reason for reason in comparison["gate_reasons"])
    overview = client.get("/api/v1/overview", headers=auth).json()
    assert any(item["decision"] == "fail" for item in overview["comparisons"])
    assert any(item["case_key"] == "release-main" and item["metric"] == "faithfulness" for item in overview["regressions"])
    assert all(item["metric_name"] != "safety" for item in overview["metric_averages"] or [])


def test_equivalent_runs_pass():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=JSONL, name="same")
    first = _run(auth, uploaded["version_id"], _target(auth, owner["project_id"], "same-a"), ["exact_match"])
    second = _run(auth, uploaded["version_id"], _target(auth, owner["project_id"], "same-b"), ["exact_match"])
    process_run(first["run_id"])
    process_run(second["run_id"])
    policy_id = _policy(auth, owner["project_id"], "allow", {"exact_match": 0})
    created = _experiment(auth, owner["project_id"], "same-check", policy_id, first["run_id"], second["run_id"])
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["decision"] == "pass"
    assert body["comparison"]["warning"] is None
    assert body["comparison"]["dataset_versions_equivalent"] is True


def test_evaluator_config_difference_is_review():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=JSONL, name="config")
    first = _run(auth, uploaded["version_id"], _target(auth, owner["project_id"], "config-a"), ["exact_match"])
    process_run(first["run_id"])
    with session_scope() as session:
        session.add(
            EvaluatorConfig(
                project_id=uuid.UUID(owner["project_id"]),
                name="exact_match",
                version="1",
                config={"note": "changed"},
            )
        )
    second = _run(auth, uploaded["version_id"], _target(auth, owner["project_id"], "config-b"), ["exact_match"])
    process_run(second["run_id"])
    policy_id = _policy(auth, owner["project_id"], "config-policy", {"exact_match": 0})
    created = _experiment(auth, owner["project_id"], "config-check", policy_id, first["run_id"], second["run_id"])
    assert created.status_code == 201, created.text
    assert created.json()["decision"] == "review"
    assert created.json()["comparison"]["evaluator_differences"]


def test_unfinished_run_is_not_comparable():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=JSONL, name="queued")
    first = _run(auth, uploaded["version_id"], _target(auth, owner["project_id"], "queued-a"), ["exact_match"])
    second = _run(auth, uploaded["version_id"], _target(auth, owner["project_id"], "queued-b"), ["exact_match"])
    policy_id = _policy(auth, owner["project_id"], "queued-policy", {"exact_match": 0})
    created = _experiment(auth, owner["project_id"], "queued-check", policy_id, first["run_id"], second["run_id"])
    assert created.status_code == 409
    assert created.json()["error"]["code"] == "validation_error"

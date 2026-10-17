"""Worker claim, recovery, cancellation, and a real Celery run."""

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from backend.app.db import session_scope
from backend.app.models import CaseAttempt, CaseResult, MetricResult, TestCase
from evaluator.tests.test_api import JSONL, _register, _target, _token, _upload, client
from worker.execution import process_run
from worker.recovery import recover_runs


def _evaluation(auth: dict, version_id: str, target_id: str) -> dict:
    response = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={
            "dataset_version_id": version_id,
            "target_id": target_id,
            "evaluator_names": ["exact_match"],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "queued"
    return body


def _counts(run_id: str) -> tuple[int, int, int]:
    run_uuid = uuid.UUID(run_id)
    with session_scope() as session:
        results = int(
            session.scalar(select(func.count()).select_from(CaseResult).where(CaseResult.run_id == run_uuid)) or 0
        )
        metrics = int(
            session.scalar(select(func.count()).select_from(MetricResult).where(MetricResult.run_id == run_uuid)) or 0
        )
        attempts = int(
            session.scalar(select(func.count()).select_from(CaseAttempt).where(CaseAttempt.run_id == run_uuid)) or 0
        )
    return results, metrics, attempts


def test_duplicate_process_run_writes_one_score():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"])
    target = _target(auth, owner["project_id"])
    created = _evaluation(auth, uploaded["version_id"], target["id"])

    process_run(created["run_id"])
    process_run(created["run_id"])

    assert _counts(created["run_id"]) == (1, 1, 1)
    finished = client.get(f"/api/v1/evaluations/{created['run_id']}", headers=auth)
    assert finished.status_code == 200
    assert finished.json()["status"] == "completed"


def test_cancel_after_first_batch_keeps_finished_results():
    owner = _register()
    auth = _token(owner)
    lines = [
        json.dumps({"id": f"case-{index:02d}", "input": f"question {index}", "expected_output": "ok"})
        for index in range(15)
    ]
    uploaded = _upload(auth, owner["project_id"], content="\n".join(lines) + "\n")
    target = _target(auth, owner["project_id"])
    created = _evaluation(auth, uploaded["version_id"], target["id"])

    process_run(created["run_id"], max_batches=1)
    cancelled = client.post(f"/api/v1/evaluations/{created['run_id']}/cancel", headers=auth)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    process_run(created["run_id"])

    results, _metrics, attempts = _counts(created["run_id"])
    assert results == 10
    assert attempts == 10
    finished = client.get(f"/api/v1/evaluations/{created['run_id']}", headers=auth).json()
    assert finished["status"] == "cancelled"

    again = client.post(f"/api/v1/evaluations/{created['run_id']}/cancel", headers=auth)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "validation_error"

    stranger = _register()
    missing = client.post(
        f"/api/v1/evaluations/{created['run_id']}/cancel",
        headers=_token(stranger),
    )
    assert missing.status_code == 404


def test_expired_claim_is_completed_once():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=JSONL)
    target = _target(auth, owner["project_id"])
    created = _evaluation(auth, uploaded["version_id"], target["id"])
    with session_scope() as session:
        case = session.scalar(
            select(TestCase).where(TestCase.dataset_version_id == uuid.UUID(uploaded["version_id"]))
        )
        assert case is not None
        session.add(
            CaseAttempt(
                run_id=uuid.UUID(created["run_id"]),
                test_case_id=case.id,
                status="claimed",
                heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )

    published = recover_runs(0)
    assert created["run_id"] in published
    deadline = time.time() + 90
    status = "queued"
    while time.time() < deadline:
        status = client.get(f"/api/v1/evaluations/{created['run_id']}", headers=auth).json()["status"]
        if status in {"completed", "partial"}:
            break
        time.sleep(0.5)

    assert status == "completed"
    assert _counts(created["run_id"]) == (1, 1, 1)


def test_worker_finishes_one_hundred_mock_cases():
    owner = _register()
    auth = _token(owner)
    lines = []
    for index in range(100):
        case_id = f"case-{index:03d}"
        if index == 0:
            case_id = "case-timeout"
        elif index == 1:
            case_id = "case-rate-limit"
        elif index == 2:
            case_id = "case-wrong"
        lines.append(json.dumps({"id": case_id, "input": f"question {index}", "expected_output": "ok"}))
    uploaded = _upload(auth, owner["project_id"], content="\n".join(lines) + "\n")
    target = _target(auth, owner["project_id"])
    os.environ["EVALFORGE_ENQUEUE_RUNS"] = "true"
    try:
        created = _evaluation(auth, uploaded["version_id"], target["id"])
    finally:
        os.environ["EVALFORGE_ENQUEUE_RUNS"] = "false"

    deadline = time.time() + 120
    body = {"status": "queued", "summary": None}
    while time.time() < deadline:
        body = client.get(f"/api/v1/evaluations/{created['run_id']}", headers=auth).json()
        if body["status"] in {"partial", "completed", "cancelled"}:
            break
        time.sleep(0.5)

    assert body["status"] == "partial"
    summary = body["summary"]
    assert summary["timeout_count"] == 1
    assert summary["rate_limit_count"] == 1
    assert summary["quality_fail_count"] == 1
    assert summary["case_count"] == 100
    assert _counts(created["run_id"])[0] == 100

"""Outbox recovery, token budgets, inbox deduplication, and metrics."""

import json
import uuid

from backend.app.db import session_scope
from backend.app.models import KafkaInbox, OutboxEvent, Workspace
from evaluator.tests.test_api import JSONL, _register, _token, _upload, client
from worker.execution import _claim_batch, process_run
from worker.kafka_bus import record_inbox
from worker.recovery import drain_outbox


def test_outbox_recovery_runs_without_a_direct_publish():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=JSONL)
    target = client.post(
        "/api/v1/targets",
        headers=auth,
        json={
            "project_id": owner["project_id"],
            "name": f"outbox-{uuid.uuid4().hex[:8]}",
            "adapter_type": "mock",
            "config": {"model": "mock-v1"},
            "prompt_version": "prompt-1",
        },
    )
    assert target.status_code == 201, target.text
    created = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={
            "dataset_version_id": uploaded["version_id"],
            "target_id": target.json()["id"],
            "evaluator_names": ["exact_match"],
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    with session_scope() as session:
        event = session.query(OutboxEvent).filter(OutboxEvent.run_id == uuid.UUID(run_id)).one()
        assert event.published_at is None
    assert run_id in drain_outbox(force=True)
    deadline_status = "queued"
    import time

    for _ in range(40):
        deadline_status = client.get(f"/api/v1/evaluations/{run_id}", headers=auth).json()["status"]
        if deadline_status in {"completed", "partial"}:
            break
        time.sleep(0.5)
    assert deadline_status == "completed"


def test_spent_budget_refuses_a_new_run_and_stops_the_next_batch():
    owner = _register()
    auth = _token(owner)
    with session_scope() as session:
        workspace = session.get(Workspace, uuid.UUID(owner["workspace_id"]))
        assert workspace is not None
        workspace.token_budget = 0
    uploaded = _upload(auth, owner["project_id"], content=JSONL)
    target = client.post(
        "/api/v1/targets",
        headers=auth,
        json={
            "project_id": owner["project_id"],
            "name": f"budget-{uuid.uuid4().hex[:8]}",
            "adapter_type": "mock",
            "config": {"model": "mock-v1"},
            "prompt_version": "prompt-1",
        },
    )
    refused = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={
            "dataset_version_id": uploaded["version_id"],
            "target_id": target.json()["id"],
            "evaluator_names": ["exact_match"],
        },
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "quota_exceeded"

    with session_scope() as session:
        workspace = session.get(Workspace, uuid.UUID(owner["workspace_id"]))
        workspace.token_budget = 1
    lines = "\n".join(
        json.dumps({"id": f"case-{index:03d}", "input": "question", "expected_output": "ok"})
        for index in range(11)
    )
    wide = _upload(auth, owner["project_id"], content=lines + "\n", name="wide")
    created = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={
            "dataset_version_id": wide["version_id"],
            "target_id": target.json()["id"],
            "evaluator_names": ["exact_match"],
        },
    )
    assert created.status_code == 201, created.text
    process_run(created.json()["run_id"])
    body = client.get(f"/api/v1/evaluations/{created.json()['run_id']}", headers=auth).json()
    assert body["status"] == "partial"
    assert body["summary"]["budget_reason"] == "workspace token budget reached"


def test_a_second_run_waits_while_one_is_running():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=JSONL)
    first_target = client.post(
        "/api/v1/targets",
        headers=auth,
        json={
            "project_id": owner["project_id"],
            "name": f"run-a-{uuid.uuid4().hex[:8]}",
            "adapter_type": "mock",
            "config": {"model": "mock-v1"},
            "prompt_version": "prompt-1",
        },
    ).json()["id"]
    second_target = client.post(
        "/api/v1/targets",
        headers=auth,
        json={
            "project_id": owner["project_id"],
            "name": f"run-b-{uuid.uuid4().hex[:8]}",
            "adapter_type": "mock",
            "config": {"model": "mock-v1"},
            "prompt_version": "prompt-1",
        },
    ).json()["id"]
    first = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={"dataset_version_id": uploaded["version_id"], "target_id": first_target, "evaluator_names": ["exact_match"]},
    ).json()["run_id"]
    second = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={"dataset_version_id": uploaded["version_id"], "target_id": second_target, "evaluator_names": ["exact_match"]},
    ).json()["run_id"]
    assert _claim_batch(first)
    assert _claim_batch(second) is None
    assert client.get(f"/api/v1/evaluations/{second}", headers=auth).json()["status"] == "queued"


def test_kafka_inbox_ignores_a_duplicate_event():
    event_id = uuid.uuid4().hex
    with session_scope() as session:
        assert record_inbox(session, event_id) is True
    with session_scope() as session:
        assert record_inbox(session, event_id) is False
        assert session.get(KafkaInbox, event_id) is not None


def test_metrics_include_queue_and_http_series():
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200, response.text
    body = response.text
    assert "evalforge_queue_depth" in body
    assert "evalforge_http_requests_total" in body

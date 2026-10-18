"""Agent traces, tool metrics, and owner approval of a review."""

import uuid
from pathlib import Path

from sqlalchemy import select

from backend.app.db import session_scope
from backend.app.models import Membership
from evaluator.tests.test_api import JSONL, _register, _token, _upload, client
from worker.execution import process_run

AGENT = Path("sample_datasets/agent.jsonl").read_text(encoding="utf-8")
TOOL_METRICS = [
    "tool_selection",
    "tool_arguments",
    "tool_permission",
    "tool_recovery",
    "tool_unnecessary",
]


def _target(auth: dict, project_id: str, adapter_type: str, name: str) -> str:
    response = client.post(
        "/api/v1/targets",
        headers=auth,
        json={
            "project_id": project_id,
            "name": name,
            "adapter_type": adapter_type,
            "config": {},
            "prompt_version": "prompt-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _run(auth: dict, version_id: str, target_id: str, evaluators: list[str]) -> str:
    created = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={"dataset_version_id": version_id, "target_id": target_id, "evaluator_names": evaluators},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    process_run(run_id)
    return run_id


def test_forbidden_tool_fails_permission_and_keeps_exact_match():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=AGENT, name=f"agent-{uuid.uuid4().hex[:8]}")
    target_id = _target(auth, owner["project_id"], "langgraph", f"graph-{uuid.uuid4().hex[:8]}")
    run_id = _run(auth, uploaded["version_id"], target_id, ["exact_match", "tool_permission"])
    cases = client.get(f"/api/v1/evaluations/{run_id}/cases", headers=auth).json()["cases"]
    forbidden = next(item for item in cases if item["case_key"] == "agent-forbidden")
    metrics = {item["metric_name"]: item for item in forbidden["metrics"]}
    assert metrics["tool_permission"]["status"] == "failed"
    assert metrics["exact_match"]["status"] == "passed"
    assert any(step.get("name") == "transfer_funds" for step in forbidden["trace"]["steps"])


def test_allowed_tool_passes_tool_metrics_and_task_completion():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=AGENT, name=f"agent-{uuid.uuid4().hex[:8]}")
    target_id = _target(auth, owner["project_id"], "langgraph", f"graph-{uuid.uuid4().hex[:8]}")
    run_id = _run(auth, uploaded["version_id"], target_id, [*TOOL_METRICS, "task_completion"])
    cases = client.get(f"/api/v1/evaluations/{run_id}/cases", headers=auth).json()["cases"]
    ok = next(item for item in cases if item["case_key"] == "agent-ok")
    assert {item["metric_name"] for item in ok["metrics"]} == set(TOOL_METRICS + ["task_completion"])
    assert all(item["status"] == "passed" for item in ok["metrics"])
    task = next(item for item in ok["metrics"] if item["metric_name"] == "task_completion")
    assert task["details"]["goal"] == "Read the demo balance"
    overview = client.get("/api/v1/overview", headers=auth).json()
    names = {item["metric_name"] for item in overview["metric_averages"] or []}
    assert names.isdisjoint(TOOL_METRICS)


def test_missing_trace_is_a_metric_error():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=JSONL)
    target_id = _target(auth, owner["project_id"], "mock", f"mock-{uuid.uuid4().hex[:8]}")
    run_id = _run(auth, uploaded["version_id"], target_id, ["tool_recovery"])
    cases = client.get(f"/api/v1/evaluations/{run_id}/cases", headers=auth).json()["cases"]
    assert cases[0]["execution_status"] == "succeeded"
    assert cases[0]["metrics"][0]["status"] == "metric_error"
    assert cases[0]["trace"] is None


def test_only_the_owner_can_approve_a_new_version():
    owner = _register()
    auth = _token(owner)
    member = _register()
    with session_scope() as session:
        membership = session.scalar(select(Membership).where(Membership.user_id == uuid.UUID(member["user_id"])))
        membership.workspace_id = uuid.UUID(owner["workspace_id"])
        membership.role = "member"
    uploaded = _upload(auth, owner["project_id"], content=AGENT, name=f"agent-{uuid.uuid4().hex[:8]}")
    target_id = _target(auth, owner["project_id"], "langgraph", f"graph-{uuid.uuid4().hex[:8]}")
    run_id = _run(auth, uploaded["version_id"], target_id, ["tool_permission"])
    queued = client.post(
        "/api/v1/reviews",
        headers=_token(member),
        json={"run_id": run_id, "case_key": "agent-forbidden", "labels": {"tool_permission": "failed"}},
    )
    assert queued.status_code == 201, queued.text
    denied = client.post(f"/api/v1/reviews/{queued.json()['id']}/approve", headers=_token(member))
    assert denied.status_code == 403
    approved = client.post(f"/api/v1/reviews/{queued.json()['id']}/approve", headers=auth)
    assert approved.status_code == 200, approved.text
    assert approved.json()["version_number"] == 2
    original = client.get(f"/api/v1/datasets/{uploaded['dataset_id']}/versions/1", headers=auth).json()
    copied = client.get(f"/api/v1/datasets/{uploaded['dataset_id']}/versions/2", headers=auth).json()
    original_case = next(item for item in original["cases"] if item["case_key"] == "agent-forbidden")
    copied_case = next(item for item in copied["cases"] if item["case_key"] == "agent-forbidden")
    assert original_case["human_labels"] is None
    assert copied_case["human_labels"]["tool_permission"] == "failed"

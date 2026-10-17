import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.db import session_scope
from backend.app.main import app
from backend.app.models import DatasetVersion, EvaluationRun, TargetConfig
from backend.app.services.inline import InlineExecutionDisabled, execute_inline
from evaluator.metrics.deterministic import ExactMatchEvaluator
from evaluator.types import EvaluationCase

client = TestClient(app)
JSONL = '{"id":"qa-001","input":"How do I reset my password?","expected_output":"Use the reset page."}\n'


def _token(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['token']}"}


def _register() -> dict:
    suffix = uuid.uuid4().hex
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"user-{suffix}@example.com",
            "password": "password-123",
            "workspace_name": f"workspace-{suffix}",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload(auth: dict, project_id: str, content: str = JSONL, name: str | None = None) -> dict:
    response = client.post(
        "/api/v1/datasets",
        headers=auth,
        data={"dataset_name": name or f"support-{uuid.uuid4().hex[:8]}", "project_id": project_id},
        files={"file": ("cases.jsonl", content.encode("utf-8"), "application/jsonl")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _target(auth: dict, project_id: str) -> dict:
    response = client.post(
        "/api/v1/targets",
        headers=auth,
        json={
            "project_id": project_id,
            "name": f"mock-{uuid.uuid4().hex[:8]}",
            "adapter_type": "mock",
            "config": {"model": "mock-v1"},
            "prompt_version": "prompt-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _count(model) -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_second_user_cannot_read_another_workspace_dataset_or_run():
    first = _register()
    second = _register()
    uploaded = _upload(_token(first), first["project_id"])
    target = _target(_token(first), first["project_id"])
    created = client.post(
        "/api/v1/evaluations",
        headers=_token(first),
        json={
            "dataset_version_id": uploaded["version_id"],
            "target_id": target["id"],
            "evaluator_names": ["exact_match"],
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    dataset = client.get(f"/api/v1/datasets/{uploaded['dataset_id']}", headers=_token(second))
    run = client.get(f"/api/v1/evaluations/{run_id}", headers=_token(second))
    assert dataset.status_code == 404
    assert dataset.json()["error"]["code"] == "invalid_dataset"
    assert run.status_code == 404
    assert run.json()["error"]["code"] == "unknown_run"
    assert dataset.json()["error"]["message"] == run.json()["error"]["message"]


def test_malformed_jsonl_returns_line_numbers_and_writes_nothing():
    owner = _register()
    before = _count(DatasetVersion)
    response = client.post(
        "/api/v1/datasets",
        headers=_token(owner),
        data={"dataset_name": "broken", "project_id": owner["project_id"]},
        files={"file": ("cases.jsonl", '{"id":"ok","input":"q","expected_output":"a"}\n{\n'.encode(), "application/jsonl")},
    )
    assert response.status_code == 400
    body = response.json()["error"]
    assert body["code"] == "invalid_dataset"
    assert any(item["line"] == 2 for item in body["details"])
    assert _count(DatasetVersion) == before


def test_queued_run_snapshot_survives_target_edits_and_does_not_execute():
    owner = _register()
    uploaded = _upload(_token(owner), owner["project_id"])
    target = _target(_token(owner), owner["project_id"])
    created = client.post(
        "/api/v1/evaluations",
        headers=_token(owner),
        json={
            "dataset_version_id": uploaded["version_id"],
            "target_id": target["id"],
            "evaluator_names": ["exact_match", "latency"],
        },
    )
    assert created.status_code == 201
    assert created.json() == {
        "run_id": created.json()["run_id"],
        "status": "queued",
        "message": "Evaluation accepted",
    }
    run_id = created.json()["run_id"]

    with session_scope() as session:
        row = session.get(TargetConfig, uuid.UUID(target["id"]))
        assert row is not None
        row.config = {"prompt_version": "edited", "model": "changed"}

    stored = client.get(f"/api/v1/evaluations/{run_id}", headers=_token(owner))
    assert stored.status_code == 200
    snapshot = stored.json()["snapshot"]
    assert snapshot["target_config"]["model"] == "mock-v1"
    assert snapshot["prompt_version"] == "prompt-1"
    assert snapshot["evaluators"][0]["name"] == "exact_match"
    cases = client.get(f"/api/v1/evaluations/{run_id}/cases", headers=_token(owner))
    assert cases.status_code == 200
    assert cases.json()["cases"] == []


def test_missing_token_and_unsupported_evaluator_do_not_create_a_run():
    missing = client.get(f"/api/v1/datasets/{uuid.uuid4()}")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"

    owner = _register()
    uploaded = _upload(_token(owner), owner["project_id"])
    target = _target(_token(owner), owner["project_id"])
    before = _count(EvaluationRun)
    rejected = client.post(
        "/api/v1/evaluations",
        headers=_token(owner),
        json={
            "dataset_version_id": uploaded["version_id"],
            "target_id": target["id"],
            "evaluator_names": ["json_schema"],
        },
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "unsupported_evaluator"
    assert _count(EvaluationRun) == before

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "password-123"},
    )
    assert login.status_code == 401
    assert login.json()["error"]["code"] == "unauthorized"


def test_twenty_first_queued_run_is_rejected():
    owner = _register()
    uploaded = _upload(_token(owner), owner["project_id"])
    target = _target(_token(owner), owner["project_id"])
    payload = {
        "dataset_version_id": uploaded["version_id"],
        "target_id": target["id"],
        "evaluator_names": ["exact_match"],
    }
    for _ in range(20):
        response = client.post("/api/v1/evaluations", headers=_token(owner), json=payload)
        assert response.status_code == 201, response.text
    rejected = client.post("/api/v1/evaluations", headers=_token(owner), json=payload)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "quota_exceeded"


def test_inline_execution_stays_disabled_on_the_product_path():
    case = EvaluationCase(case_key="c1", input_text="question", expected_output="question")
    with pytest.raises(InlineExecutionDisabled):
        execute_inline([case], [ExactMatchEvaluator()])
    monkey_name = "EVALFORGE_ALLOW_INLINE_EXECUTION"
    import os

    os.environ[monkey_name] = "true"
    try:
        results = execute_inline([case], [ExactMatchEvaluator()])
    finally:
        os.environ.pop(monkey_name, None)
    assert results[0].execution_status == "succeeded"
    assert results[0].scores[0].status == "passed"

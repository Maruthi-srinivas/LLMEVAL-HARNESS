"""Tenant isolation, roles, export approval, SSRF, and retention."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.app.db import session_scope
from backend.app.models import EvaluationRun
from backend.app.services.artifacts import report_exists
from backend.app.services.retention import purge_expired
from evaluator.net import UnsafeTargetUrl, ensure_safe_url, redirected
from evaluator.tests.test_api import JSONL, _register, _token, _upload, client
from worker.execution import process_run


def _headers(auth: dict, workspace_id: str) -> dict:
    return {**auth, "X-EvalForge-Workspace": workspace_id}


def _join(owner_auth: dict, role: str) -> dict:
    invited = _register()
    created = client.post("/api/v1/invites", headers=owner_auth, json={"role": role})
    assert created.status_code == 201, created.text
    accepted = client.post(f"/api/v1/invites/{created.json()['token']}/accept", headers=_token(invited))
    assert accepted.status_code == 200, accepted.text
    return invited


def test_other_organization_cannot_read_a_run_report_or_export():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"])
    target = client.post(
        "/api/v1/targets",
        headers=auth,
        json={"project_id": owner["project_id"], "name": f"t-{uuid.uuid4().hex[:6]}", "adapter_type": "mock", "config": {"model": "mock-v1"}, "prompt_version": "p"},
    )
    created = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={"dataset_version_id": uploaded["version_id"], "target_id": target.json()["id"], "evaluator_names": ["exact_match"]},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    process_run(run_id)
    export = client.post(f"/api/v1/datasets/{uploaded['dataset_id']}/exports", headers=auth)
    assert export.status_code == 201, export.text
    other = _token(_register())
    assert client.get(f"/api/v1/evaluations/{run_id}", headers=other).status_code == 404
    assert client.get(f"/api/v1/evaluations/{run_id}/report", headers=other).status_code == 404
    assert client.get(f"/api/v1/exports/{export.json()['id']}", headers=other).status_code == 404
    events = client.get("/api/v1/audit", headers=other).json()["events"]
    assert all(item["resource_id"] != run_id for item in events)


def test_roles_limit_writes_and_service_tokens_cannot_approve():
    owner = _register()
    auth = _token(owner)
    viewer = _join(auth, "viewer")
    member = _join(auth, "member")
    viewer_headers = _headers(_token(viewer), owner["workspace_id"])
    member_headers = _headers(_token(member), owner["workspace_id"])
    assert client.post(
        "/api/v1/datasets",
        headers=viewer_headers,
        data={"dataset_name": "hidden", "project_id": owner["project_id"]},
        files={"file": ("cases.jsonl", JSONL.encode(), "application/jsonl")},
    ).status_code == 403
    uploaded = _upload(auth, owner["project_id"])
    target = client.post(
        "/api/v1/targets",
        headers=auth,
        json={"project_id": owner["project_id"], "name": f"t-{uuid.uuid4().hex[:6]}", "adapter_type": "mock", "config": {"model": "mock-v1"}, "prompt_version": "p"},
    ).json()["id"]
    assert client.post(
        "/api/v1/evaluations",
        headers=viewer_headers,
        json={"dataset_version_id": uploaded["version_id"], "target_id": target, "evaluator_names": ["exact_match"]},
    ).status_code == 403
    assert client.patch("/api/v1/workspaces/retention", headers=member_headers, json={"retention_days": 7}).status_code == 403
    assert client.post("/api/v1/service-accounts", headers=member_headers, json={"name": "ci"}).status_code == 403
    token = client.post("/api/v1/service-accounts", headers=auth, json={"name": "ci"})
    assert token.status_code == 201, token.text
    service = {"Authorization": f"Bearer {token.json()['token']}"}
    run_id = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={"dataset_version_id": uploaded["version_id"], "target_id": target, "evaluator_names": ["exact_match"]},
    ).json()["run_id"]
    process_run(run_id)
    review = client.post("/api/v1/reviews", headers=member_headers, json={"run_id": run_id, "case_key": "qa-001", "labels": {"exact_match": "passed"}})
    assert review.status_code == 201, review.text
    assert client.post(f"/api/v1/reviews/{review.json()['id']}/approve", headers=service).status_code == 403


def test_dataset_export_waits_for_the_owner():
    owner = _register()
    auth = _token(owner)
    member = _join(auth, "member")
    member_headers = _headers(_token(member), owner["workspace_id"])
    uploaded = _upload(auth, owner["project_id"], content='{"id":"qa-001","input":"How do I reset my password?","expected_output":"Use the reset page."}\n')
    created = client.post(f"/api/v1/datasets/{uploaded['dataset_id']}/exports", headers=member_headers)
    assert created.status_code == 201, created.text
    export_id = created.json()["id"]
    assert client.get(f"/api/v1/exports/{export_id}", headers=member_headers).status_code == 403
    approved = client.post(f"/api/v1/exports/{export_id}/approve", headers=auth)
    assert approved.status_code == 200, approved.text
    downloaded = client.get(f"/api/v1/exports/{export_id}", headers=member_headers)
    assert downloaded.status_code == 200, downloaded.text
    assert "qa-001" in downloaded.text


def test_audit_covers_login_import_run_export_policy_and_deletion():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"])
    target = client.post(
        "/api/v1/targets",
        headers=auth,
        json={"project_id": owner["project_id"], "name": f"t-{uuid.uuid4().hex[:6]}", "adapter_type": "mock", "config": {"model": "mock-v1"}, "prompt_version": "p"},
    ).json()["id"]
    client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={"dataset_version_id": uploaded["version_id"], "target_id": target, "evaluator_names": ["exact_match"]},
    )
    export = client.post(f"/api/v1/datasets/{uploaded['dataset_id']}/exports", headers=auth)
    client.post(f"/api/v1/exports/{export.json()['id']}/approve", headers=auth)
    policy = client.post(
        "/api/v1/policies",
        headers=auth,
        json={
            "project_id": owner["project_id"],
            "name": f"policy-{uuid.uuid4().hex[:6]}",
            "metric_minimums": {"exact_match": 1},
            "max_error_rate": 0.5,
            "latency_budget_ms": 1000,
            "safety_required": False,
            "price_per_1k_tokens": 0,
            "max_cost_increase": 1,
        },
    )
    assert policy.status_code == 201, policy.text
    fresh = _upload(auth, owner["project_id"])
    deleted = client.delete(f"/api/v1/datasets/{fresh['dataset_id']}", headers=auth)
    assert deleted.status_code == 204, deleted.text
    actions = {item["action"] for item in client.get("/api/v1/audit", headers=auth).json()["events"]}
    assert {"login", "dataset_import", "run_creation", "export", "policy_change", "deletion"} <= actions


def test_private_targets_are_blocked_and_the_rag_host_is_allowed():
    for url in ("http://127.0.0.1/answer", "http://10.1.1.1/answer"):
        try:
            ensure_safe_url(url)
        except UnsafeTargetUrl:
            continue
        raise AssertionError(url)
    ensure_safe_url("http://rag/answer")
    try:
        redirected("http://rag/answer", "http://127.0.0.1/secret")
    except UnsafeTargetUrl:
        return
    raise AssertionError("redirect was accepted")


def test_retention_removes_an_old_run_and_keeps_a_new_one():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"])
    target = client.post(
        "/api/v1/targets",
        headers=auth,
        json={"project_id": owner["project_id"], "name": f"t-{uuid.uuid4().hex[:6]}", "adapter_type": "mock", "config": {"model": "mock-v1"}, "prompt_version": "p"},
    ).json()["id"]
    run_ids = []
    for _ in range(2):
        created = client.post(
            "/api/v1/evaluations",
            headers=auth,
            json={"dataset_version_id": uploaded["version_id"], "target_id": target, "evaluator_names": ["exact_match"]},
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["run_id"]
        process_run(run_id)
        run_ids.append(run_id)
    assert client.patch("/api/v1/workspaces/retention", headers=auth, json={"retention_days": 1}).status_code == 200
    with session_scope() as session:
        old = session.get(EvaluationRun, uuid.UUID(run_ids[0]))
        old.finished_at = datetime.now(timezone.utc) - timedelta(days=3)
        workspace_id = old.project_id
    with session_scope() as session:
        run = session.get(EvaluationRun, uuid.UUID(run_ids[0]))
        from backend.app.models import Project

        workspace = session.get(Project, run.project_id).workspace_id
        assert report_exists(workspace, run.id)
        assert purge_expired(session) == 1
        assert session.get(EvaluationRun, uuid.UUID(run_ids[0])) is None
        assert session.get(EvaluationRun, uuid.UUID(run_ids[1])) is not None
        assert not report_exists(workspace, uuid.UUID(run_ids[0]))
    del workspace_id


def test_fixture_oidc_login_creates_a_workspace():
    response = client.get("/api/v1/auth/oidc/callback", params={"code": "fixture-code", "state": "demo"})
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "owner"
    assert response.json()["organization_id"]

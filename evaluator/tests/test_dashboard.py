"""Dashboard reads, overview numbers, and report export."""

import csv
import io
import uuid

from evaluator.tests.test_api import _register, _target, _token, _upload, client
from worker.execution import process_run

FAILING = (
    '{"id":"case-ok","input":"hello","expected_output":"ok"}\n'
    '{"id":"case-wrong","input":"refund","expected_output":"ok"}\n'
)


def _start(auth: dict, version_id: str, target_id: str) -> dict:
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
    return response.json()


def test_second_workspace_cannot_list_or_export():
    owner = _register()
    other = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=FAILING, name=f"dash-{uuid.uuid4().hex[:8]}")
    target = _target(auth, owner["project_id"])
    created = _start(auth, uploaded["version_id"], target["id"])

    listed = client.get("/api/v1/datasets", headers=_token(other))
    assert listed.status_code == 200
    assert all(item["id"] != uploaded["dataset_id"] for item in listed.json()["datasets"])

    foreign = client.get(f"/api/v1/evaluations/{created['run_id']}/report", headers=_token(other))
    assert foreign.status_code == 404


def test_overview_keeps_missing_measurements_null():
    owner = _register()
    response = client.get("/api/v1/overview", headers=_token(owner))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["estimated_cost"] is None
    assert body["estimated_cost_reason"] == "no price configured"
    assert body["latency_ms_median"] is None
    assert body["latency_ms_p95"] is None
    assert body["metric_averages"] is None
    assert body["token_usage"] is None
    assert body["scope"]["workspace_id"] == owner["workspace_id"]
    assert body["generated_at"]
    assert "later version" in body["later_note"]


def test_finished_run_exports_json_and_one_failed_csv_row():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=FAILING)
    target = _target(auth, owner["project_id"])
    created = _start(auth, uploaded["version_id"], target["id"])

    queued = client.get(f"/api/v1/evaluations/{created['run_id']}/report", headers=auth)
    assert queued.status_code == 409
    assert queued.json()["error"]["code"] == "validation_error"

    process_run(created["run_id"])

    document = client.get(f"/api/v1/evaluations/{created['run_id']}/report?format=json", headers=auth)
    assert document.status_code == 200, document.text
    report = document.json()
    assert report["status"] == "completed"
    wrong = [case for case in report["cases"] if case["case_key"] == "case-wrong"]
    assert len(wrong) == 1
    assert wrong[0]["expected_output"] == "ok"
    assert wrong[0]["metrics"][0]["status"] == "failed"

    table = client.get(f"/api/v1/evaluations/{created['run_id']}/report?format=csv", headers=auth)
    assert table.status_code == 200
    rows = list(csv.DictReader(io.StringIO(table.text)))
    failed = [row for row in rows if row["case_key"] == "case-wrong" and row["metric_status"] == "failed"]
    assert len(failed) == 1

    detail = client.get(f"/api/v1/evaluations/{created['run_id']}", headers=auth).json()
    assert "progress" in detail
    listed = client.get("/api/v1/evaluations", headers=auth).json()["runs"]
    assert any(item["run_id"] == created["run_id"] for item in listed)

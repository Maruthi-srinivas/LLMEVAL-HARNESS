"""Safety scoring, the evaluator registry, and calibration disagreements."""

from pathlib import Path

from evaluator.tests.test_api import JSONL, _register, _token, _upload, client
from worker.execution import process_run

CALIBRATION = (
    '{"id":"case-ok","input":"hello","expected_output":"ok","human_labels":{"exact_match":"passed"}}\n'
    '{"id":"case-wrong","input":"refund","expected_output":"ok","human_labels":{"exact_match":"passed"}}\n'
)


def _target(auth: dict, project_id: str, config: dict) -> str:
    response = client.post(
        "/api/v1/targets",
        headers=auth,
        json={
            "project_id": project_id,
            "name": f"target-{config.get('behavior', 'default')}",
            "adapter_type": "mock",
            "config": config,
            "prompt_version": "prompt-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _start(auth: dict, version_id: str, target_id: str, evaluators: list[str]) -> dict:
    response = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={"dataset_version_id": version_id, "target_id": target_id, "evaluator_names": evaluators},
    )
    return response


def test_registry_lists_safety_and_structured_output_contracts():
    owner = _register()
    response = client.get("/api/v1/evaluators", headers=_token(owner))
    assert response.status_code == 200, response.text
    by_name = {item["name"]: item for item in response.json()["evaluators"]}
    assert by_name["safety"]["required_inputs"] == ["expected_policy"]
    assert by_name["safety"]["score_range"] == {"min": 0.0, "max": 1.0}
    assert "quality failure" in by_name["safety"]["failure_behavior"]
    assert by_name["structured_output"]["required_inputs"] == ["json_schema"]
    assert "judge_model" in by_name["faithfulness"]["config_schema"]["properties"]


def test_recall_selection_requires_relevant_ids():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=JSONL)
    target_id = _target(auth, owner["project_id"], {"model": "mock-v1"})
    response = _start(auth, uploaded["version_id"], target_id, ["recall_at_5"])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_evaluator"


def test_refuse_all_fails_valid_requests_and_passes_refusals():
    owner = _register()
    auth = _token(owner)
    content = Path("sample_datasets/safety.jsonl").read_text(encoding="utf-8")
    uploaded = _upload(auth, owner["project_id"], content=content, name="safety")
    target_id = _target(auth, owner["project_id"], {"model": "mock-v1", "behavior": "refuse_all"})
    created = _start(auth, uploaded["version_id"], target_id, ["safety"])
    assert created.status_code == 201, created.text
    process_run(created.json()["run_id"])
    cases = client.get(f"/api/v1/evaluations/{created.json()['run_id']}/cases", headers=auth).json()["cases"]
    valid = next(item for item in cases if item["case_key"] == "safety-valid")
    refusal = next(item for item in cases if item["case_key"] == "safety-override")
    assert valid["metrics"][0]["metric_name"] == "safety"
    assert valid["metrics"][0]["status"] == "failed"
    assert valid["metrics"][0]["details"]["expected_policy"] == "answer"
    assert valid["metrics"][0]["details"]["policy_outcome"] == "mismatched"
    assert refusal["metrics"][0]["status"] == "passed"
    assert refusal["metrics"][0]["details"]["policy_outcome"] == "matched"
    overview = client.get("/api/v1/overview", headers=auth).json()
    assert overview["safety"]["failed"] >= 1
    assert overview["safety"]["passed"] >= 1
    assert overview["metric_averages"] is None or all(item["metric_name"] != "safety" for item in overview["metric_averages"])


def test_calibration_lists_the_disagreeing_case():
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=CALIBRATION)
    target_id = _target(auth, owner["project_id"], {"model": "mock-v1"})
    created = _start(auth, uploaded["version_id"], target_id, ["exact_match"])
    assert created.status_code == 201, created.text
    queued = client.post(
        f"/api/v1/datasets/{uploaded['dataset_id']}/calibration",
        headers=auth,
        json={"run_id": created.json()["run_id"], "evaluator_names": ["exact_match"]},
    )
    assert queued.status_code == 409
    process_run(created.json()["run_id"])
    report = client.post(
        f"/api/v1/datasets/{uploaded['dataset_id']}/calibration",
        headers=auth,
        json={"run_id": created.json()["run_id"], "evaluator_names": ["exact_match"]},
    )
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["match_rate"] < 1
    assert any(item["case_key"] == "case-wrong" for item in body["disagreements"])

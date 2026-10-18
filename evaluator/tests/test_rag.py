"""RAG metrics, the mock judge, and the HTTP adapter contract."""

import json

import httpx

from evaluator.adapters.http_rag import HttpRagAdapter
from evaluator.tests.test_api import _register, _token, _upload, client
from worker.execution import process_run

FIXTURE = "\n".join(
    [
        json.dumps(
            {
                "id": "case-missing-docs",
                "input": "Where is the policy?",
                "expected_output": "It is documented.",
                "relevant_document_ids": ["doc-1", "doc-2"],
            }
        ),
        json.dumps(
            {
                "id": "case-unsupported",
                "input": "What is the refund policy?",
                "expected_output": "Refunds are available within 30 days.",
                "relevant_document_ids": ["doc-1"],
                "citations": [{"document_id": "doc-1", "claim": "Refunds are available within 30 days."}],
            }
        ),
        json.dumps(
            {
                "id": "case-bad-judge",
                "input": "Explain the account.",
                "expected_output": "The account is active.",
                "relevant_document_ids": ["doc-1"],
            }
        ),
        json.dumps(
            {
                "id": "case-timeout",
                "input": "This request times out.",
                "expected_output": "unused",
                "relevant_document_ids": ["doc-1"],
            }
        ),
    ]
) + "\n"


def _run(content: str, evaluators: list[str], adapter_type: str = "mock", config: dict | None = None) -> tuple[dict, dict]:
    owner = _register()
    auth = _token(owner)
    uploaded = _upload(auth, owner["project_id"], content=content)
    target = client.post(
        "/api/v1/targets",
        headers=auth,
        json={
            "project_id": owner["project_id"],
            "name": f"{adapter_type}-target",
            "adapter_type": adapter_type,
            "config": config or {"model": "mock-v1"},
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
            "evaluator_names": evaluators,
        },
    )
    assert created.status_code == 201, created.text
    process_run(created.json()["run_id"])
    body = client.get(f"/api/v1/evaluations/{created.json()['run_id']}", headers=auth)
    cases = client.get(f"/api/v1/evaluations/{created.json()['run_id']}/cases", headers=auth)
    return body.json(), cases.json()


def _case(payload: dict, case_key: str) -> dict:
    return next(item for item in payload["cases"] if item["case_key"] == case_key)


def _metric(case: dict, name: str) -> dict:
    return next(item for item in case["metrics"] if item["metric_name"] == name)


def test_missing_documents_lower_recall_without_scoring_a_timeout():
    run, cases = _run(FIXTURE, ["recall_at_5", "exact_match"])
    assert run["status"] == "partial"
    missing = _case(cases, "case-missing-docs")
    recall = _metric(missing, "recall_at_5")
    assert recall["score"] == 0
    assert recall["status"] == "failed"
    assert missing["retrieved_documents"] == [{"id": "doc-9", "text": "This document is not relevant."}]
    timed_out = _case(cases, "case-timeout")
    assert timed_out["execution_status"] == "execution_error"
    assert timed_out["error_category"] == "timeout"
    assert timed_out["metrics"] == []


def test_unsupported_claim_fails_faithfulness_and_keeps_exact_match():
    line = next(line for line in FIXTURE.splitlines() if "case-unsupported" in line)
    run, cases = _run(line + "\n", ["faithfulness", "exact_match"])
    assert run["status"] == "completed"
    unsupported = _case(cases, "case-unsupported")
    assert unsupported["execution_status"] == "succeeded"
    assert _metric(unsupported, "exact_match")["status"] == "passed"
    faith = _metric(unsupported, "faithfulness")
    assert faith["status"] == "failed"
    assert faith["details"]["judge_model"] == "mock-judge"
    assert faith["details"]["evidence"]
    assert unsupported["retrieved_documents"][0]["id"] == "doc-1"
    snapshot = run["snapshot"]["evaluators"]
    recorded = next(item for item in snapshot if item["name"] == "faithfulness")
    assert recorded["config"]["judge_model"] == "mock-judge"
    assert recorded["config"]["rubric_version"] == "1"


def test_invalid_judge_json_is_a_metric_error():
    line = next(line for line in FIXTURE.splitlines() if "case-bad-judge" in line)
    _run_body, cases = _run(line + "\n", ["faithfulness"])
    bad = _case(cases, "case-bad-judge")
    assert bad["execution_status"] == "succeeded"
    assert _metric(bad, "faithfulness")["status"] == "metric_error"


def test_unknown_adapter_records_provider_error_without_scores():
    _run_body, cases = _run(
        '{"id":"qa","input":"q","expected_output":"a","relevant_document_ids":["doc-1"]}\n',
        ["exact_match"],
        adapter_type="openai",
    )
    case = _case(cases, "qa")
    assert case["execution_status"] == "execution_error"
    assert case["error_category"] == "provider_error"
    assert case["metrics"] == []


def test_http_rag_adapter_uses_the_fixed_contract():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "answer": "It is documented.",
                "documents": [{"id": "doc-1", "text": "The policy is documented."}],
                "token_usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )

    import asyncio

    result = asyncio.run(
        HttpRagAdapter("http://rag.example/answer", transport=httpx.MockTransport(handler)).invoke("Where?", {})
    )
    assert seen["body"] == {"question": "Where?"}
    assert result.output == "It is documented."
    assert result.documents == [{"id": "doc-1", "text": "The policy is documented."}]
    assert result.error_category is None

    def bad(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "x"})

    rejected = asyncio.run(
        HttpRagAdapter("http://rag.example/answer", transport=httpx.MockTransport(bad)).invoke("Where?", {})
    )
    assert rejected.error_category == "provider_error"
    assert rejected.documents == []

"""Sample evaluation command. Run this inside the runner container."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from backend.app.db import session_scope
from evaluator.adapters.mock import MockTargetAdapter
from evaluator.datasets.loader import DatasetValidationError, default_sample_path, load_jsonl
from evaluator.metrics.deterministic import default_sample_evaluators
from evaluator.runner import IncompatibleConfiguration, execute, final_status, validate_configuration
from evaluator.store import (
    case_ids_by_key,
    create_run,
    ensure_dataset_version,
    ensure_demo_graph,
    finalize_run,
    mark_running,
    persist_case,
)


@dataclass(frozen=True)
class SampleRunResult:
    run_id: uuid.UUID
    status: str
    dataset_version_id: uuid.UUID
    summary: dict


def run_sample(path: Path | None = None) -> SampleRunResult:
    dataset_path = path or default_sample_path()
    cases = load_jsonl(dataset_path)
    evaluators = default_sample_evaluators()
    validate_configuration(cases, evaluators)
    adapter = MockTargetAdapter.for_sample(cases)

    with session_scope() as session:
        project, target = ensure_demo_graph(session, evaluators)
        version = ensure_dataset_version(session, project.id, cases)
        run = create_run(session, project, version, target, evaluators)
        run_id = run.id
        version_id = version.id

    results = asyncio.run(execute(cases, adapter, evaluators))
    status, summary = final_status(results)

    with session_scope() as session:
        from backend.app.models import EvaluationRun

        run = session.get(EvaluationRun, run_id)
        if run is None:
            raise RuntimeError(f"Run {run_id} disappeared before execution")
        mark_running(session, run)
        session.commit()
        ids = case_ids_by_key(session, version_id)
        for result in results:
            persist_case(session, run_id, ids[result.case_key], result)
            session.commit()
        finalize_run(session, run, status, summary)

    return SampleRunResult(
        run_id=run_id,
        status=status,
        dataset_version_id=version_id,
        summary=summary,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="evaluator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run-sample")
    run_parser.add_argument("--dataset", type=Path, default=None)
    decide_parser = subparsers.add_parser("decide")
    decide_parser.add_argument("--dataset", type=Path, required=True)
    decide_parser.add_argument("--baseline-dataset", type=Path, default=None)
    decide_parser.add_argument("--adapter", default="mock")
    decide_parser.add_argument("--behavior", default="default")
    decide_parser.add_argument("--baseline-behavior", default="default")
    decide_parser.add_argument("--endpoint", default="")
    decide_parser.add_argument("--evaluators", default="safety")
    decide_parser.add_argument("--metric-minimums", default='{"safety": 1}')
    decide_parser.add_argument("--api-url", default=None)
    args = parser.parse_args(argv)
    if args.command == "run-sample":
        try:
            result = run_sample(args.dataset)
        except (DatasetValidationError, IncompatibleConfiguration) as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        print(
            json.dumps(
                {
                    "run_id": str(result.run_id),
                    "status": result.status,
                    "dataset_version_id": str(result.dataset_version_id),
                    "summary": result.summary,
                }
            )
        )
        return
    raise SystemExit(decide(args))


_CODES = {"pass": 0, "fail": 1, "review": 3}


def decide(args) -> int:
    import os
    import time
    import uuid

    import httpx

    base = args.api_url or os.environ.get("API_URL", "http://api:8000")
    suffix = uuid.uuid4().hex[:8]
    with httpx.Client(base_url=base, timeout=30) as client:
        registered = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"cli-{suffix}@example.com",
                "password": "password-123",
                "workspace_name": f"cli-{suffix}",
            },
        )
        registered.raise_for_status()
        owner = registered.json()
        auth = {"Authorization": f"Bearer {owner['token']}"}
        baseline_path = args.baseline_dataset or args.dataset
        baseline_id = _launch(
            client,
            auth,
            owner["project_id"],
            baseline_path,
            f"suite-{suffix}",
            f"baseline-{suffix}",
            args.baseline_behavior,
            "mock",
            "",
            args.evaluators,
        )
        candidate_id = _launch(
            client,
            auth,
            owner["project_id"],
            args.dataset,
            f"suite-{suffix}",
            f"candidate-{suffix}",
            args.behavior,
            args.adapter,
            args.endpoint,
            args.evaluators,
        )
        _wait(client, auth, baseline_id)
        _wait(client, auth, candidate_id)
        cases = client.get(f"/api/v1/evaluations/{candidate_id}/cases", headers=auth).json()["cases"]
        if cases and all(_infrastructure(case) for case in cases):
            print(json.dumps({"decision": "infrastructure_fail", "run_id": candidate_id}))
            return 2
        policy = client.post(
            "/api/v1/policies",
            headers=auth,
            json={
                "project_id": owner["project_id"],
                "name": f"policy-{suffix}",
                "metric_minimums": json.loads(args.metric_minimums),
                "max_error_rate": 1,
                "latency_budget_ms": 10000,
                "safety_required": True,
                "price_per_1k_tokens": 0,
                "max_cost_increase": 100000,
            },
        )
        policy.raise_for_status()
        experiment = client.post(
            "/api/v1/experiments",
            headers=auth,
            json={
                "project_id": owner["project_id"],
                "name": f"experiment-{suffix}",
                "policy_id": policy.json()["id"],
                "baseline_run_id": baseline_id,
                "candidate_run_id": candidate_id,
            },
        )
        experiment.raise_for_status()
        body = experiment.json()
        print(json.dumps({"decision": body["decision"], "experiment_id": body["id"], "run_id": candidate_id}))
        return _CODES[body["decision"]]


def _infrastructure(case: dict) -> bool:
    return (
        case.get("execution_status") == "execution_error"
        and case.get("error_category") in {"provider_error", "timeout"}
        and not case.get("metrics")
    )


def _launch(client, auth, project_id, path: Path, dataset_name: str, target_name: str, behavior: str, adapter: str, endpoint: str, evaluators: str) -> str:
    content = path.read_bytes()
    uploaded = client.post(
        "/api/v1/datasets",
        headers=auth,
        data={"dataset_name": dataset_name, "project_id": project_id},
        files={"file": (path.name, content, "application/jsonl")},
    )
    uploaded.raise_for_status()
    config = {"model": "mock-v1"}
    if adapter == "http_rag":
        config = {"endpoint": endpoint}
    elif behavior != "default":
        config["behavior"] = behavior
    target = client.post(
        "/api/v1/targets",
        headers=auth,
        json={
            "project_id": project_id,
            "name": target_name,
            "adapter_type": adapter if adapter == "http_rag" else "mock",
            "config": config,
            "prompt_version": "prompt-1",
        },
    )
    target.raise_for_status()
    created = client.post(
        "/api/v1/evaluations",
        headers=auth,
        json={
            "dataset_version_id": uploaded.json()["version_id"],
            "target_id": target.json()["id"],
            "evaluator_names": [item.strip() for item in evaluators.split(",") if item.strip()],
        },
    )
    created.raise_for_status()
    return created.json()["run_id"]


def _wait(client, auth, run_id: str) -> None:
    import time

    status = "queued"
    for _ in range(90):
        if status in {"completed", "partial", "cancelled"}:
            return
        time.sleep(1)
        status = client.get(f"/api/v1/evaluations/{run_id}", headers=auth).json()["status"]
    raise SystemExit(f"run {run_id} stayed {status}")


if __name__ == "__main__":
    main()

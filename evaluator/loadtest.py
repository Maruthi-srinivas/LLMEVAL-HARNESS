"""Five concurrent mock runs, one workspace each. A duplicate case row fails the drill."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

API = __import__("os").environ.get("API_URL", "http://api:8000")
DATASET = Path("sample_datasets/support_qa.jsonl")
if not DATASET.exists():
    DATASET = Path("sample_datasets/support-qa.jsonl")


def _one(index: int) -> str:
    suffix = uuid.uuid4().hex[:8]
    with httpx.Client(base_url=API, timeout=30) as client:
        owner = client.post(
            "/api/v1/auth/register",
            json={"email": f"load-{index}-{suffix}@example.com", "password": "password-123", "workspace_name": f"load-{index}-{suffix}"},
        )
        owner.raise_for_status()
        body = owner.json()
        headers = {"Authorization": f"Bearer {body['token']}"}
        uploaded = client.post(
            "/api/v1/datasets",
            headers=headers,
            data={"dataset_name": f"load-{suffix}", "project_id": body["project_id"]},
            files={"file": ("cases.jsonl", DATASET.read_bytes(), "application/jsonl")},
        )
        uploaded.raise_for_status()
        target = client.post(
            "/api/v1/targets",
            headers=headers,
            json={"project_id": body["project_id"], "name": f"load-{suffix}", "adapter_type": "mock", "config": {"model": "mock-v1"}, "prompt_version": "load"},
        )
        target.raise_for_status()
        created = client.post(
            "/api/v1/evaluations",
            headers=headers,
            json={"dataset_version_id": uploaded.json()["version_id"], "target_id": target.json()["id"], "evaluator_names": ["exact_match"]},
        )
        created.raise_for_status()
        run_id = created.json()["run_id"]
        for _ in range(60):
            current = client.get(f"/api/v1/evaluations/{run_id}", headers=headers)
            current.raise_for_status()
            if current.json()["status"] in {"completed", "partial", "cancelled"}:
                break
            __import__("time").sleep(1)
        else:
            raise SystemExit(f"run {run_id} did not finish")
        cases = client.get(f"/api/v1/evaluations/{run_id}/cases", headers=headers).json()["cases"]
        keys = [item["case_key"] for item in cases]
        if len(keys) != len(set(keys)) or not keys:
            raise SystemExit(f"duplicate or empty cases for {run_id}")
        return run_id


def main() -> None:
    with ThreadPoolExecutor(max_workers=5) as pool:
        run_ids = list(pool.map(_one, range(5)))
    print("ok", " ".join(run_ids))


if __name__ == "__main__":
    main()

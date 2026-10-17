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


if __name__ == "__main__":
    main()

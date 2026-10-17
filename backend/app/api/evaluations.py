"""Evaluation routes. Creation stores a queued run and returns immediately."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_principal
from backend.app.errors import APIError
from backend.app.schemas import EvaluationCreate
from backend.app.services.access import Principal, require_dataset_version, require_run, require_target
from backend.app.services.evaluations import case_results, create_queued_run
from evaluator.status import transition

router = APIRouter(tags=["evaluations"])
_FINISHED = {"completed", "partial", "cancelled"}


@router.post("/evaluations", status_code=201)
def create_evaluation(
    body: EvaluationCreate,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    _dataset, version = require_dataset_version(session, principal.workspace.id, body.dataset_version_id)
    target = require_target(session, principal.workspace.id, body.target_id)
    run = create_queued_run(session, version, target, body.evaluator_names)
    run_id = str(run.id)
    background_tasks.add_task(_publish_after_commit, run_id)
    return {"run_id": run_id, "status": run.status, "message": "Evaluation accepted"}


def _publish_after_commit(run_id: str) -> None:
    from worker.tasks import publish_run

    publish_run(run_id)


@router.post("/evaluations/{run_id}/cancel")
def cancel_evaluation(
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    run = require_run(session, principal.workspace.id, run_id)
    if run.status in _FINISHED:
        raise APIError(409, "validation_error", "Run is already finished")
    if run.status not in {"queued", "running"}:
        raise APIError(409, "validation_error", "Run cannot be cancelled")
    run.status = transition(run.status, "cancel")
    return {"run_id": str(run.id), "status": run.status}


@router.get("/evaluations/{run_id}")
def read_evaluation(
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    run = require_run(session, principal.workspace.id, run_id)
    return {
        "run_id": str(run.id),
        "status": run.status,
        "snapshot": run.snapshot,
        "summary": run.summary,
    }


@router.get("/evaluations/{run_id}/cases")
def read_evaluation_cases(
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    run = require_run(session, principal.workspace.id, run_id)
    return {"run_id": str(run.id), "cases": case_results(session, run.id)}

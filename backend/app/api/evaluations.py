"""Evaluation routes. Creation stores a queued run and returns immediately."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_principal
from backend.app.errors import APIError
from backend.app.schemas import EvaluationCreate
from backend.app.services.access import Principal, require_dataset_version, require_run, require_target, require_writer
from backend.app.services.artifacts import object_key, report_exists
from backend.app.services.audit import record
from backend.app.services.evaluations import case_results, create_queued_run, list_runs
from backend.app.services.reports import csv_report, json_report
from evaluator.status import transition

router = APIRouter(tags=["evaluations"])
_FINISHED = {"completed", "partial", "cancelled"}


@router.post("/evaluations", status_code=201)
def create_evaluation(
    body: EvaluationCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    require_writer(principal)
    _dataset, version = require_dataset_version(session, principal.workspace.id, body.dataset_version_id)
    target = require_target(session, principal.workspace.id, body.target_id)
    run = create_queued_run(session, version, target, body.evaluator_names)
    record(session, principal, "run_creation", "evaluation_run", str(run.id))
    return {"run_id": str(run.id), "status": run.status, "message": "Evaluation accepted"}


@router.get("/evaluations")
def read_evaluations(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return {"runs": list_runs(session, principal.workspace.id)}


@router.post("/evaluations/{run_id}/cancel")
def cancel_evaluation(
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    require_writer(principal)
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
        "progress": run.progress,
        "started_at": None if run.started_at is None else run.started_at.isoformat(),
        "finished_at": None if run.finished_at is None else run.finished_at.isoformat(),
    }


@router.get("/evaluations/{run_id}/cases")
def read_evaluation_cases(
    run_id: UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    run = require_run(session, principal.workspace.id, run_id)
    return {"run_id": str(run.id), "cases": case_results(session, run.id)}


@router.get("/evaluations/{run_id}/report")
def read_evaluation_report(
    run_id: UUID,
    format: str = Query(default="json"),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
):
    run = require_run(session, principal.workspace.id, run_id)
    if format == "json":
        body = json_report(session, run)
        key = object_key(principal.workspace.id, run.id)
        body["artifact_key"] = key if report_exists(principal.workspace.id, run.id) else None
        return body
    if format == "csv":
        return Response(
            content=csv_report(session, run),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="run-{run.id}.csv"'},
        )
    raise APIError(422, "validation_error", "format must be json or csv")

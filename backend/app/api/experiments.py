"""Release policies and stored experiment comparisons."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_principal
from backend.app.schemas import ExperimentCreate, PolicyCreate
from backend.app.services.access import Principal
from backend.app.services.experiments import (
    create_experiment,
    create_policy,
    experiment_payload,
    list_experiments,
    list_policies,
    policy_payload,
    read_experiment,
)

router = APIRouter(tags=["experiments"])


@router.post("/policies", status_code=201)
def post_policy(
    body: PolicyCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return policy_payload(create_policy(session, principal.workspace.id, body))


@router.get("/policies")
def get_policies(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return {"policies": list_policies(session, principal.workspace.id)}


@router.post("/experiments", status_code=201)
def post_experiment(
    body: ExperimentCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return experiment_payload(create_experiment(session, principal.workspace.id, body))


@router.get("/experiments")
def get_experiments(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return {"experiments": list_experiments(session, principal.workspace.id)}


@router.get("/experiments/{experiment_id}")
def get_experiment(
    experiment_id: UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return read_experiment(session, principal.workspace.id, experiment_id)

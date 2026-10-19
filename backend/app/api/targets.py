"""Target configuration routes."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_principal
from backend.app.errors import APIError
from backend.app.models import TargetConfig
from backend.app.schemas import TargetCreate
from backend.app.services.access import Principal, require_project, require_target, require_writer

router = APIRouter(tags=["targets"])


@router.post("/targets", status_code=201)
def create_target(
    body: TargetCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    require_writer(principal)
    project = require_project(session, principal.workspace.id, body.project_id, "validation_error")
    config = dict(body.config)
    config["prompt_version"] = body.prompt_version
    target = TargetConfig(
        project_id=project.id,
        name=body.name,
        adapter_type=body.adapter_type,
        config=config,
    )
    session.add(target)
    try:
        session.flush()
    except Exception as exc:
        from sqlalchemy.exc import IntegrityError

        if isinstance(exc, IntegrityError):
            raise APIError(400, "validation_error", "Target name is already in use") from exc
        raise
    return _target_body(target)


@router.get("/targets/{target_id}")
def read_target(
    target_id: UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    target = require_target(session, principal.workspace.id, target_id)
    return _target_body(target)


def _target_body(target: TargetConfig) -> dict:
    prompt_version = target.config.get("prompt_version") if isinstance(target.config, dict) else None
    return {
        "id": str(target.id),
        "project_id": str(target.project_id),
        "name": target.name,
        "adapter_type": target.adapter_type,
        "config": target.config,
        "prompt_version": prompt_version,
    }

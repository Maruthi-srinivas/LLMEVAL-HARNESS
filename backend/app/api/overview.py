"""Workspace inspection summary."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_principal
from backend.app.models import Organization
from backend.app.services.access import Principal
from backend.app.services.overview import workspace_overview

router = APIRouter(tags=["overview"])


@router.get("/overview")
def read_overview(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    organization = session.get(Organization, principal.workspace.organization_id)
    name = organization.name if organization is not None else ""
    return workspace_overview(session, principal.workspace.id, principal.workspace.name, name)

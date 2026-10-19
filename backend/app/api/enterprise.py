"""Invites, service accounts, retention, and the audit log."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_principal
from backend.app.schemas import InviteCreate, RetentionUpdate, ServiceAccountCreate
from backend.app.services.access import Principal
from backend.app.services.audit import list_events
from backend.app.services.identity import accept_invite, create_invite, create_service_account, update_retention

router = APIRouter(tags=["enterprise"])


@router.post("/invites", status_code=201)
def post_invite(
    body: InviteCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return create_invite(session, principal, body.role)


@router.post("/invites/{token}/accept")
def post_accept(
    token: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return accept_invite(session, principal, token)


@router.post("/service-accounts", status_code=201)
def post_service_account(
    body: ServiceAccountCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return create_service_account(session, principal, body.name)


@router.patch("/workspaces/retention")
def patch_retention(
    body: RetentionUpdate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return update_retention(session, principal, body.retention_days)


@router.get("/audit")
def read_audit(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return {"events": list_events(session, principal.workspace.id)}

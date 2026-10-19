"""Authentication routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas import AuthResponse, LoginRequest, RegisterRequest
from backend.app.services.accounts import login_user, membership_payloads, register_user
from backend.app.services.identity import oidc_callback, oidc_start

router = APIRouter(prefix="/auth", tags=["auth"])


def _response(session: Session, principal, token: str) -> AuthResponse:
    return AuthResponse(
        token=token,
        user_id=principal.user.id,
        workspace_id=principal.workspace.id,
        organization_id=principal.workspace.organization_id,
        project_id=principal.project.id,
        role=principal.role,
        memberships=membership_payloads(session, principal.user.id),
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(body: RegisterRequest, session: Session = Depends(get_db)) -> AuthResponse:
    principal, token = register_user(session, body.email, body.password, body.workspace_name)
    return _response(session, principal, token)


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, session: Session = Depends(get_db)) -> AuthResponse:
    principal, token = login_user(session, body.email, body.password)
    return _response(session, principal, token)


@router.get("/oidc/start")
def start_oidc() -> dict:
    return oidc_start()


@router.get("/oidc/callback", response_model=AuthResponse)
def callback_oidc(code: str, state: str = "", session: Session = Depends(get_db)) -> AuthResponse:
    principal, token = oidc_callback(session, code, state)
    return _response(session, principal, token)

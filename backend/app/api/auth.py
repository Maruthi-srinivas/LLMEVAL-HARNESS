"""Authentication routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas import AuthResponse, LoginRequest, RegisterRequest
from backend.app.services.accounts import login_user, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _response(principal, token: str) -> AuthResponse:
    return AuthResponse(
        token=token,
        user_id=principal.user.id,
        workspace_id=principal.workspace.id,
        project_id=principal.project.id,
        role=principal.role,
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(body: RegisterRequest, session: Session = Depends(get_db)) -> AuthResponse:
    principal, token = register_user(session, body.email, body.password, body.workspace_name)
    return _response(principal, token)


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, session: Session = Depends(get_db)) -> AuthResponse:
    principal, token = login_user(session, body.email, body.password)
    return _response(principal, token)

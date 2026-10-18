"""Account registration and login."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.errors import APIError
from backend.app.models import Membership, Project, User, Workspace
from backend.app.services.access import Principal, principal_for_user
from backend.app.services.passwords import create_token, hash_password, verify_password


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register_user(session: Session, email: str, password: str, workspace_name: str) -> tuple[Principal, str]:
    normalized = normalize_email(email)
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise APIError(422, "validation_error", "Email must contain a domain")
    existing = session.scalar(select(User).where(User.email == normalized))
    if existing is not None:
        raise APIError(400, "validation_error", "Email is already registered")
    taken = session.scalar(select(Workspace).where(Workspace.name == workspace_name))
    if taken is not None:
        raise APIError(400, "validation_error", "Workspace name is already in use")

    user = User(email=normalized, password_hash=hash_password(password))
    workspace = Workspace(name=workspace_name)
    session.add(user)
    session.add(workspace)
    session.flush()
    session.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    project = Project(workspace_id=workspace.id, name="default")
    session.add(project)
    try:
        session.flush()
    except IntegrityError as exc:
        raise APIError(400, "validation_error", "Account could not be created") from exc
    principal = Principal(user=user, workspace=workspace, project=project, role="owner")
    return principal, create_token(user.id)


def login_user(session: Session, email: str, password: str) -> tuple[Principal, str]:
    user = session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        raise APIError(401, "unauthorized", "Invalid email or password")
    return principal_for_user(session, user), create_token(user.id)

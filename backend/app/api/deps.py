"""FastAPI dependencies."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import session_scope
from backend.app.errors import APIError
from backend.app.models import ServiceAccount, User
from backend.app.services.access import Principal, _principal, principal_for_user
from backend.app.services.passwords import read_user_id
from backend.app.services.tokens import hash_token


def get_db() -> Iterator[Session]:
    with session_scope() as session:
        yield session


def get_principal(
    session: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_evalforge_workspace: str | None = Header(default=None),
) -> Principal:
    if authorization is None or not authorization.startswith("Bearer "):
        raise APIError(401, "unauthorized", "Authentication required")
    token = authorization.removeprefix("Bearer ").strip()
    workspace_id = _workspace_header(x_evalforge_workspace)
    user_id = read_user_id(token)
    if user_id is not None:
        user = session.get(User, user_id)
        if user is None:
            raise APIError(401, "unauthorized", "Authentication required")
        return principal_for_user(session, user, workspace_id)
    return _service_principal(session, token, workspace_id)


def _workspace_header(value: str | None) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise APIError(422, "validation_error", "Workspace header is not a valid id") from exc


def _service_principal(session: Session, token: str, workspace_id: uuid.UUID | None) -> Principal:
    account = session.scalar(select(ServiceAccount).where(ServiceAccount.token_hash == hash_token(token)))
    if account is None:
        raise APIError(401, "unauthorized", "Authentication required")
    if workspace_id is not None and workspace_id != account.workspace_id:
        raise APIError(404, "validation_error", "Resource not found")
    user = session.get(User, account.created_by)
    if user is None:
        raise APIError(401, "unauthorized", "Authentication required")
    return _principal(session, user, account.workspace_id, "service", account.id)

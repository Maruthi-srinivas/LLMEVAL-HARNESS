"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from backend.app.db import session_scope
from backend.app.errors import APIError
from backend.app.models import User
from backend.app.services.access import Principal, principal_for_user
from backend.app.services.passwords import read_user_id


def get_db() -> Iterator[Session]:
    with session_scope() as session:
        yield session


def get_principal(
    session: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Principal:
    if authorization is None or not authorization.startswith("Bearer "):
        raise APIError(401, "unauthorized", "Authentication required")
    user_id = read_user_id(authorization.removeprefix("Bearer ").strip())
    if user_id is None:
        raise APIError(401, "unauthorized", "Authentication required")
    user = session.get(User, user_id)
    if user is None:
        raise APIError(401, "unauthorized", "Authentication required")
    return principal_for_user(session, user)

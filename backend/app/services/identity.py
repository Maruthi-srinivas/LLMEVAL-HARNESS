"""Invites, service tokens, retention changes, and fixture OIDC login."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.errors import APIError
from backend.app.models import Invite, Membership, Organization, Project, ServiceAccount, User, Workspace
from backend.app.services.access import Principal, principal_for_user, require_owner
from backend.app.services.audit import record
from backend.app.services.passwords import create_token
from backend.app.services.tokens import hash_token, new_token

ISSUER = os.environ.get("OIDC_ISSUER", "http://oidc:8091")
OIDC_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "fixture-secret")
OIDC_CLIENT = os.environ.get("OIDC_CLIENT_ID", "evalforge")


def create_invite(session: Session, principal: Principal, role: str) -> dict:
    require_owner(principal)
    if role not in {"member", "viewer"}:
        raise APIError(422, "validation_error", "Invite role must be member or viewer")
    raw, digest = new_token("invite")
    invite = Invite(
        workspace_id=principal.workspace.id,
        role=role,
        token_hash=digest,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        created_by=principal.user.id,
    )
    session.add(invite)
    session.flush()
    return {"invite_id": str(invite.id), "token": raw, "role": role}


def accept_invite(session: Session, principal: Principal, token: str) -> dict:
    invite = session.scalar(select(Invite).where(Invite.token_hash == hash_token(token)))
    if invite is None or invite.accepted_by is not None or invite.expires_at < datetime.now(timezone.utc):
        raise APIError(404, "validation_error", "Resource not found")
    existing = session.scalar(
        select(Membership).where(
            Membership.user_id == principal.user.id,
            Membership.workspace_id == invite.workspace_id,
        )
    )
    if existing is not None:
        raise APIError(409, "validation_error", "You already belong to this workspace")
    session.add(Membership(user_id=principal.user.id, workspace_id=invite.workspace_id, role=invite.role))
    invite.accepted_by = principal.user.id
    session.flush()
    return {"workspace_id": str(invite.workspace_id), "role": invite.role}


def create_service_account(session: Session, principal: Principal, name: str) -> dict:
    require_owner(principal)
    raw, digest = new_token("efsa")
    account = ServiceAccount(
        workspace_id=principal.workspace.id,
        name=name,
        token_hash=digest,
        token_prefix=raw[:12],
        created_by=principal.user.id,
    )
    session.add(account)
    try:
        session.flush()
    except IntegrityError as exc:
        raise APIError(400, "validation_error", "Service account name is already in use") from exc
    return {"id": str(account.id), "name": name, "token": raw}


def update_retention(session: Session, principal: Principal, days: int) -> dict:
    require_owner(principal)
    principal.workspace.retention_days = days
    session.flush()
    return {"workspace_id": str(principal.workspace.id), "retention_days": days}


def oidc_start() -> dict:
    state = uuid.uuid4().hex
    url = (
        f"{ISSUER}/authorize?client_id={OIDC_CLIENT}"
        f"&redirect_uri=http://api:8000/api/v1/auth/oidc/callback&response_type=code&state={state}"
    )
    return {"authorization_url": url, "state": state}


def oidc_callback(session: Session, code: str, state: str) -> tuple[Principal, str]:
    del state
    if code == "":
        raise APIError(401, "unauthorized", "Authentication required")
    try:
        response = httpx.post(
            f"{ISSUER}/token",
            data={"code": code, "client_id": OIDC_CLIENT, "client_secret": OIDC_SECRET},
            timeout=5.0,
        )
        response.raise_for_status()
        payload = jwt.decode(response.json()["id_token"], OIDC_SECRET, algorithms=["HS256"])
    except Exception as exc:
        raise APIError(401, "unauthorized", "Authentication required") from exc
    email = str(payload.get("email") or "").strip().lower()
    if "@" not in email:
        raise APIError(401, "unauthorized", "Authentication required")
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = _oidc_user(session, email)
    principal = principal_for_user(session, user)
    record(session, principal, "login", "user", str(user.id))
    return principal, create_token(user.id)


def _oidc_user(session: Session, email: str) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(email=email, password_hash=None)
    organization = Organization(name=f"oidc-{suffix}-org")
    session.add(user)
    session.add(organization)
    session.flush()
    workspace = Workspace(name=f"oidc-{suffix}", organization_id=organization.id)
    session.add(workspace)
    session.flush()
    session.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    session.add(Project(workspace_id=workspace.id, name="default"))
    session.flush()
    return user

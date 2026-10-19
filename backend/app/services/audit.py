"""Append-only audit events. Readers only see their own workspace."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import AuditEvent
from backend.app.services.access import Principal


def record(
    session: Session,
    principal: Principal,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=principal.workspace.organization_id,
            workspace_id=principal.workspace.id,
            actor_id=principal.user.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )


def list_events(session: Session, workspace_id: uuid.UUID) -> list[dict]:
    rows = session.scalars(
        select(AuditEvent).where(AuditEvent.workspace_id == workspace_id).order_by(AuditEvent.created_at.asc())
    ).all()
    return [
        {
            "id": str(row.id),
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "actor_id": None if row.actor_id is None else str(row.actor_id),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]

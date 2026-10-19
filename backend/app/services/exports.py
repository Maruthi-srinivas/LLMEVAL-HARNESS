"""Dataset JSONL leaves the workspace only after an owner approves it."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import APIError
from backend.app.models import DatasetVersion, ExportRequest
from backend.app.services.access import Principal, require_dataset, require_owner, require_writer
from backend.app.services.audit import record
from backend.app.services.datasets import cases_for_version


def request_export(session: Session, principal: Principal, dataset_id: uuid.UUID) -> dict:
    require_writer(principal)
    dataset = require_dataset(session, principal.workspace.id, dataset_id)
    version = session.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.version_number.desc())
    )
    if version is None:
        raise APIError(404, "invalid_dataset", "Resource not found")
    row = ExportRequest(dataset_version_id=version.id, status="pending", requested_by=principal.user.id)
    session.add(row)
    session.flush()
    return {"id": str(row.id), "status": row.status, "dataset_id": str(dataset.id)}


def approve_export(session: Session, principal: Principal, export_id: uuid.UUID) -> dict:
    require_owner(principal)
    row = _in_workspace(session, principal.workspace.id, export_id)
    row.status = "approved"
    row.approved_by = principal.user.id
    session.flush()
    record(session, principal, "export", "dataset_export", str(row.id))
    return {"id": str(row.id), "status": row.status}


def download_export(session: Session, principal: Principal, export_id: uuid.UUID) -> str:
    if principal.role not in {"owner", "member", "service"}:
        raise APIError(403, "forbidden", "This action requires a member")
    row = _in_workspace(session, principal.workspace.id, export_id)
    if row.status != "approved":
        raise APIError(403, "forbidden", "This export is waiting for the owner")
    lines = []
    for case in cases_for_version(session, row.dataset_version_id):
        lines.append(
            json.dumps(
                {"id": case.case_key, "input": case.input_text, "expected_output": case.expected_output},
                separators=(",", ":"),
            )
        )
    record(session, principal, "export", "dataset_export", str(row.id))
    return "\n".join(lines) + ("\n" if lines else "")


def _in_workspace(session: Session, workspace_id: uuid.UUID, export_id: uuid.UUID) -> ExportRequest:
    found = session.execute(
        select(ExportRequest, DatasetVersion)
        .join(DatasetVersion, ExportRequest.dataset_version_id == DatasetVersion.id)
        .where(ExportRequest.id == export_id)
    ).one_or_none()
    if found is None:
        raise APIError(404, "invalid_dataset", "Resource not found")
    export, version = found
    require_dataset(session, workspace_id, version.dataset_id)
    return export

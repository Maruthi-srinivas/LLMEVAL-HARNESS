"""Dataset routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_principal
from backend.app.errors import APIError, dataset_error_details
from backend.app.services.access import Principal, require_dataset, require_project
from backend.app.services.datasets import cases_for_version, import_cases, version_summaries
from evaluator.datasets.loader import MAX_DATASET_BYTES, DatasetValidationError, load_jsonl_text

router = APIRouter(tags=["datasets"])


@router.post("/datasets", status_code=201)
async def upload_dataset(
    file: UploadFile = File(...),
    dataset_name: str = Form(...),
    project_id: UUID = Form(...),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    if not dataset_name.strip() or len(dataset_name) > 200:
        raise APIError(422, "validation_error", "dataset_name must be 1 to 200 characters")
    project = require_project(session, principal.workspace.id, project_id, "invalid_dataset")
    raw = await file.read()
    if len(raw) > MAX_DATASET_BYTES:
        raise APIError(400, "invalid_dataset", f"File exceeds {MAX_DATASET_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise APIError(400, "invalid_dataset", "File must be UTF-8 JSONL") from exc
    try:
        cases = load_jsonl_text(text)
    except DatasetValidationError as exc:
        raise APIError(
            400,
            "invalid_dataset",
            "Dataset validation failed",
            dataset_error_details(exc.errors),
        ) from exc
    dataset, version, case_count = import_cases(session, project, dataset_name.strip(), cases)
    return {
        "dataset_id": str(dataset.id),
        "version_id": str(version.id),
        "version_number": version.version_number,
        "case_count": case_count,
        "content_hash": version.content_hash,
    }


@router.get("/datasets/{dataset_id}")
def read_dataset(
    dataset_id: UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    dataset = require_dataset(session, principal.workspace.id, dataset_id)
    return {
        "id": str(dataset.id),
        "name": dataset.name,
        "project_id": str(dataset.project_id),
        "versions": version_summaries(session, dataset.id),
    }


@router.get("/datasets/{dataset_id}/versions/{version_number}")
def read_dataset_version(
    dataset_id: UUID,
    version_number: int,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    dataset = require_dataset(session, principal.workspace.id, dataset_id)
    from sqlalchemy import select

    from backend.app.models import DatasetVersion

    version = session.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset.id,
            DatasetVersion.version_number == version_number,
        )
    )
    if version is None:
        raise APIError(404, "invalid_dataset", "Resource not found")
    return {
        "dataset_id": str(dataset.id),
        "version_id": str(version.id),
        "version_number": version.version_number,
        "content_hash": version.content_hash,
        "cases": [
            {
                "id": str(case.id),
                "case_key": case.case_key,
                "input": case.input_text,
                "expected_output": case.expected_output,
                "context": case.context,
                "tags": case.tags,
                "json_schema": case.json_schema,
            }
            for case in cases_for_version(session, version.id)
        ],
    }

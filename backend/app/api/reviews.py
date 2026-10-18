"""Queue a case review and let the workspace owner approve it."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_principal
from backend.app.schemas import ReviewCreate
from backend.app.services.access import Principal
from backend.app.services.reviews import approve_review, queue_review

router = APIRouter(tags=["reviews"])


@router.post("/reviews", status_code=201)
def post_review(
    body: ReviewCreate,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return queue_review(session, principal, body.run_id, body.case_key, body.labels)


@router.post("/reviews/{review_id}/approve")
def post_approval(
    review_id: UUID,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
) -> dict:
    return approve_review(session, principal, review_id)

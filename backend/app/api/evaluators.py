"""Evaluator contracts. The registry is the source of the list."""

from fastapi import APIRouter, Depends

from backend.app.api.deps import get_principal
from backend.app.services.access import Principal
from backend.app.services.evaluations import evaluator_contracts

router = APIRouter(tags=["evaluators"])


@router.get("/evaluators")
def read_evaluators(_principal: Principal = Depends(get_principal)) -> dict:
    return {"evaluators": evaluator_contracts()}

"""Request and response models for the product API."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    workspace_name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class AuthResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    user_id: UUID
    workspace_id: UUID
    project_id: UUID
    role: str


class TargetCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    adapter_type: str = Field(min_length=1, max_length=64)
    config: dict = Field(default_factory=dict)
    prompt_version: str = Field(min_length=1, max_length=64)


class ReviewCreate(BaseModel):
    run_id: UUID
    case_key: str = Field(min_length=1)
    labels: dict[str, str]


class EvaluationCreate(BaseModel):
    dataset_version_id: UUID
    target_id: UUID
    evaluator_names: list[str] = Field(min_length=1)


class CalibrationRequest(BaseModel):
    run_id: UUID
    evaluator_names: list[str] = Field(min_length=1)


class PolicyCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    metric_minimums: dict[str, float] = Field(default_factory=dict)
    max_error_rate: float = Field(ge=0, le=1)
    latency_budget_ms: float = Field(ge=0)
    safety_required: bool = True
    price_per_1k_tokens: float = Field(ge=0)
    max_cost_increase: float = Field(ge=0)


class ExperimentCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    baseline_run_id: UUID
    candidate_run_id: UUID
    policy_id: UUID

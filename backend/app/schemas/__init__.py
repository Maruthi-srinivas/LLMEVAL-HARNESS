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


class TargetCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=200)
    adapter_type: str = Field(min_length=1, max_length=64)
    config: dict = Field(default_factory=dict)
    prompt_version: str = Field(min_length=1, max_length=64)


class EvaluationCreate(BaseModel):
    dataset_version_id: UUID
    target_id: UUID
    evaluator_names: list[str] = Field(min_length=1)

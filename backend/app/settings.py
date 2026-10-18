"""Runtime settings. Values are read on each call so tests can change them."""

from __future__ import annotations

import os

MAX_DATASET_CASES = 1000
MAX_QUEUED_RUNS = 20
TOKEN_TTL_HOURS = 24


def secret_key() -> str:
    return os.environ.get("SECRET_KEY", "dev-only-change-me")


def allow_inline_execution() -> bool:
    return os.environ.get("EVALFORGE_ALLOW_INLINE_EXECUTION", "false").lower() in {"1", "true", "yes"}


def enqueue_runs_enabled() -> bool:
    return os.environ.get("EVALFORGE_ENQUEUE_RUNS", "true").lower() in {"1", "true", "yes"}


def kafka_bootstrap() -> str:
    return os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()


def capture_content() -> bool:
    return os.environ.get("EVAL_CAPTURE_CONTENT", "false").lower() in {"1", "true", "yes"}


def cors_origin() -> str:
    return os.environ.get("EVALFORGE_CORS_ORIGIN", "http://localhost:3000")

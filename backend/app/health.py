"""Health payload shared by the API and unit tests."""

from __future__ import annotations

import os

from redis import Redis
from sqlalchemy import text

from backend.app.db import get_engine


def build_health_body(postgres_ok: bool, redis_ok: bool) -> tuple[int, dict]:
    ok = postgres_ok and redis_ok
    return (
        200 if ok else 503,
        {
            "status": "ok" if ok else "unavailable",
            "checks": {
                "postgres": "ok" if postgres_ok else "unavailable",
                "redis": "ok" if redis_ok else "unavailable",
            },
        },
    )


def ping_postgres() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def ping_redis() -> bool:
    try:
        client = Redis.from_url(
            os.environ["REDIS_URL"],
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        return client.ping() is True
    except Exception:
        return False

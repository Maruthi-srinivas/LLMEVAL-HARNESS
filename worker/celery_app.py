"""Celery application. Redis is the broker; Postgres remains the source of truth."""

import os

from celery import Celery

celery_app = Celery(
    "evalforge",
    broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
    backend=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "recover-runs": {
            "task": "worker.tasks.recover_runs",
            "schedule": 10.0,
        }
    },
)

import worker.tasks  # noqa: E402,F401

def _serve_metrics() -> None:
    from prometheus_client import start_http_server

    try:
        start_http_server(9100, addr="0.0.0.0")
    except OSError:
        return


_serve_metrics()

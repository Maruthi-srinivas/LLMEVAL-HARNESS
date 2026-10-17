"""Celery tasks. The engine stays free of broker imports."""

from worker.celery_app import celery_app
from worker.execution import process_run
from worker.recovery import recover_runs as scan_runs


def send_process_run(run_id: str) -> None:
    celery_app.send_task("worker.tasks.process_run", args=[run_id])


def publish_run(run_id: str) -> None:
    from backend.app.settings import enqueue_runs_enabled

    if not enqueue_runs_enabled():
        return
    send_process_run(run_id)


@celery_app.task(name="worker.tasks.process_run")
def process_run_task(run_id: str) -> None:
    process_run(run_id)


@celery_app.task(name="worker.tasks.recover_runs")
def recover_runs() -> list[str]:
    return scan_runs()

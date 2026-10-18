"""Prometheus series for the API and worker. Collection reads Postgres at scrape time."""

from __future__ import annotations

from datetime import datetime, timezone

from prometheus_client import Counter, Gauge, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import REGISTRY
from sqlalchemy import func, select

http_requests = Counter("evalforge_http_requests_total", "HTTP responses", ["status"])
http_latency = Histogram("evalforge_http_request_duration_seconds", "HTTP request latency")


class OperationsCollector:
    def collect(self):
        depth = GaugeMetricFamily("evalforge_queue_depth", "Queued runs")
        wait = GaugeMetricFamily("evalforge_queue_wait_seconds", "Age of the oldest queued run")
        heartbeat = GaugeMetricFamily("evalforge_heartbeat_age_seconds", "Age of the oldest running heartbeat")
        pool = GaugeMetricFamily("evalforge_db_pool_checked_out", "Checked out database connections")
        safety = GaugeMetricFamily("evalforge_safety_failures", "Failed safety metric rows")
        regressions = GaugeMetricFamily("evalforge_regression_count", "Stored pass-to-fail regressions")
        tokens = GaugeMetricFamily("evalforge_tokens_total", "Recorded input and output tokens")
        timeouts = GaugeMetricFamily("evalforge_provider_timeouts", "Provider timeouts recorded on case results")
        try:
            snapshot = _snapshot()
        except Exception:
            snapshot = {
                "depth": 0,
                "wait": 0,
                "heartbeat": 0,
                "pool": 0,
                "safety": 0,
                "regressions": 0,
                "tokens": 0,
                "timeouts": 0,
            }
        depth.add_metric([], snapshot["depth"])
        wait.add_metric([], snapshot["wait"])
        heartbeat.add_metric([], snapshot["heartbeat"])
        pool.add_metric([], snapshot["pool"])
        safety.add_metric([], snapshot["safety"])
        regressions.add_metric([], snapshot["regressions"])
        tokens.add_metric([], snapshot["tokens"])
        timeouts.add_metric([], snapshot["timeouts"])
        yield depth
        yield wait
        yield heartbeat
        yield pool
        yield safety
        yield regressions
        yield tokens
        yield timeouts


def _snapshot() -> dict[str, float]:
    from backend.app.db import session_scope
    from backend.app.models import CaseResult, EvaluationRun, Experiment, MetricResult

    now = datetime.now(timezone.utc)
    with session_scope() as session:
        queued = session.scalars(select(EvaluationRun).where(EvaluationRun.status == "queued")).all()
        running = session.scalars(select(EvaluationRun).where(EvaluationRun.status == "running")).all()
        oldest_queue = 0.0
        for run in queued:
            created = run.created_at
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created is not None:
                oldest_queue = max(oldest_queue, (now - created).total_seconds())
        oldest_heartbeat = 0.0
        for run in running:
            beat = run.heartbeat_at
            if beat is not None and beat.tzinfo is None:
                beat = beat.replace(tzinfo=timezone.utc)
            if beat is not None:
                oldest_heartbeat = max(oldest_heartbeat, (now - beat).total_seconds())
        safety_count = int(
            session.scalar(
                select(func.count()).select_from(MetricResult).where(
                    MetricResult.metric_name == "safety",
                    MetricResult.status == "failed",
                )
            )
            or 0
        )
        timeout_count = int(
            session.scalar(
                select(func.count()).select_from(CaseResult).where(CaseResult.error_category == "timeout")
            )
            or 0
        )
        regression_count = 0
        for experiment in session.scalars(select(Experiment)).all():
            stored = experiment.comparison if isinstance(experiment.comparison, dict) else {}
            regression_count += len(stored.get("regressions") or [])
        token_rows = session.scalars(select(CaseResult.token_usage)).all()
    token_total = 0.0
    for usage in token_rows:
        if not isinstance(usage, dict):
            continue
        for key in ("input_tokens", "output_tokens"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                token_total += float(value)
    pool_size = 0.0
    try:
        from backend.app.db import get_engine

        checked = getattr(get_engine().pool, "checkedout", None)
        if callable(checked):
            pool_size = float(checked())
    except Exception:
        pool_size = 0.0
    return {
        "depth": float(len(queued)),
        "wait": oldest_queue,
        "heartbeat": oldest_heartbeat,
        "pool": pool_size,
        "safety": float(safety_count),
        "regressions": float(regression_count),
        "tokens": token_total,
        "timeouts": float(timeout_count),
    }


REGISTRY.register(OperationsCollector())

# Imported for the worker process to expose the same registry.
worker_up = Gauge("evalforge_worker_up", "Worker metrics endpoint is running")
worker_up.set(1)

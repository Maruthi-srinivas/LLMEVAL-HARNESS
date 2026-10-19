"""Run reports stored in MinIO. Tests keep them in memory when no endpoint is set."""

from __future__ import annotations

import json
import os
import socket
import uuid
from urllib.parse import urlparse

_MEMORY: dict[str, bytes] = {}


def object_key(workspace_id: uuid.UUID, run_id: uuid.UUID) -> str:
    return f"reports/{workspace_id}/{run_id}.json"


def put_report(workspace_id: uuid.UUID, run_id: uuid.UUID, body: dict) -> str:
    key = object_key(workspace_id, run_id)
    payload = json.dumps(body).encode("utf-8")
    endpoint = os.environ.get("ARTIFACT_S3_ENDPOINT", "")
    if endpoint == "":
        _MEMORY[key] = payload
        return key
    if not _reachable(endpoint):
        return key
    bucket = os.environ.get("ARTIFACT_S3_BUCKET", "reports")
    remote = client()
    try:
        remote.create_bucket(Bucket=bucket)
    except Exception:
        pass
    remote.put_object(Bucket=bucket, Key=key, Body=payload, ContentType="application/json")
    return key


def delete_report(workspace_id: uuid.UUID, run_id: uuid.UUID) -> None:
    key = object_key(workspace_id, run_id)
    endpoint = os.environ.get("ARTIFACT_S3_ENDPOINT", "")
    if endpoint == "":
        _MEMORY.pop(key, None)
        return
    if not _reachable(endpoint):
        return
    client().delete_object(Bucket=os.environ.get("ARTIFACT_S3_BUCKET", "reports"), Key=key)


def report_exists(workspace_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    key = object_key(workspace_id, run_id)
    if os.environ.get("ARTIFACT_S3_ENDPOINT", "") == "":
        return key in _MEMORY
    try:
        client().head_object(Bucket=os.environ.get("ARTIFACT_S3_BUCKET", "reports"), Key=key)
        return True
    except Exception:
        return False


def _reachable(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    if not parsed.hostname:
        return False
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 9000), timeout=0.3):
            return True
    except OSError:
        return False


def client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("ARTIFACT_S3_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.environ.get("ARTIFACT_S3_ACCESS_KEY", "evalforge"),
        aws_secret_access_key=os.environ.get("ARTIFACT_S3_SECRET_KEY", "evalforge-secret"),
        region_name="us-east-1",
        config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 1}),
    )

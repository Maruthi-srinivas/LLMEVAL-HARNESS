"""JSON logs. Prompts stay out unless content capture is enabled."""

from __future__ import annotations

import json
import logging
import re

from backend.app.settings import capture_content

_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+")
_SECRET = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")

log = logging.getLogger("evalforge")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)


def redact(value: str) -> str:
    value = _SECRET.sub(r"\1[redacted]", value)
    return _EMAIL.sub("[redacted-email]", value)


def write_log(event: str, **fields: object) -> None:
    payload = {"event": event}
    for key, value in fields.items():
        if isinstance(value, str):
            payload[key] = redact(value)
        else:
            payload[key] = value
    if not capture_content():
        payload.pop("input", None)
        payload.pop("output", None)
        payload.pop("prompt", None)
    log.info(json.dumps(payload, default=str))

"""One-way hashes for invite and service-account tokens."""

from __future__ import annotations

import hashlib
import secrets


def new_token(prefix: str) -> tuple[str, str]:
    raw = f"{prefix}_{secrets.token_urlsafe(24)}"
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

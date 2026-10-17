"""Consistent API errors."""

from __future__ import annotations

import re

_LINE = re.compile(r"^Line (\d+): (.*)$")


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: list[dict] | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        super().__init__(message)


def error_body(code: str, message: str, details: list[dict] | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or []}}


def dataset_error_details(errors: list[str]) -> list[dict]:
    details = []
    for error in errors:
        match = _LINE.match(error)
        if match:
            details.append({"line": int(match.group(1)), "message": match.group(2)})
        else:
            details.append({"line": None, "message": error})
    return details

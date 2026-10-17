"""JSONL dataset loading with line-numbered errors and a size cap."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluator.types import EvaluationCase

MAX_DATASET_BYTES = 5 * 1024 * 1024
_REQUIRED = ("id", "input", "expected_output")


class DatasetValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def default_sample_path() -> Path:
    return Path(__file__).resolve().parents[2] / "sample_datasets" / "support_qa.jsonl"


def content_hash(cases: list[EvaluationCase]) -> str:
    import hashlib

    payload = [
        {
            "context": case.context,
            "expected_output": case.expected_output,
            "id": case.case_key,
            "input": case.input_text,
            "json_schema": case.json_schema,
            "tags": list(case.tags),
        }
        for case in cases
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_jsonl(path: Path, max_bytes: int = MAX_DATASET_BYTES) -> list[EvaluationCase]:
    size = path.stat().st_size
    if size > max_bytes:
        raise DatasetValidationError([f"File exceeds {max_bytes} bytes"])
    return _load_lines(_iter_lines(path))


def load_jsonl_text(text: str, max_bytes: int = MAX_DATASET_BYTES) -> list[EvaluationCase]:
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise DatasetValidationError([f"File exceeds {max_bytes} bytes"])
    return _load_lines(text.splitlines())


def _iter_lines(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        yield from handle


def _load_lines(lines) -> list[EvaluationCase]:
    errors: list[str] = []
    cases: list[EvaluationCase] = []
    seen: dict[str, int] = {}

    for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"Line {line_number}: malformed JSON ({exc.msg})")
                continue
            if not isinstance(payload, dict):
                errors.append(f"Line {line_number}: record must be a JSON object")
                continue
            case, case_errors = _parse_record(payload, line_number)
            errors.extend(case_errors)
            if case is None:
                continue
            previous = seen.get(case.case_key)
            if previous is not None:
                errors.append(
                    f"Line {line_number}: duplicate id {case.case_key!r} (first seen on line {previous})"
                )
                continue
            seen[case.case_key] = line_number
            cases.append(case)

    if not cases and not errors:
        errors.append("Dataset contains no records")
    if errors:
        raise DatasetValidationError(errors)
    return cases


def _parse_record(payload: dict[str, Any], line_number: int) -> tuple[EvaluationCase | None, list[str]]:
    errors: list[str] = []
    for field in _REQUIRED:
        value = payload.get(field)
        if not isinstance(value, str) or value == "":
            errors.append(f"Line {line_number}: missing required field {field}")
    if errors:
        return None, errors

    tags = payload.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        errors.append(f"Line {line_number}: tags must be a list of strings")

    context = payload.get("context")
    if context is not None and not isinstance(context, str):
        errors.append(f"Line {line_number}: context must be a string")

    schema = payload.get("json_schema")
    if schema is not None and not isinstance(schema, dict):
        errors.append(f"Line {line_number}: json_schema must be an object")

    if errors:
        return None, errors

    return (
        EvaluationCase(
            case_key=payload["id"],
            input_text=payload["input"],
            expected_output=payload["expected_output"],
            context=context,
            tags=tuple(tags),
            json_schema=schema,
            line_number=line_number,
        ),
        [],
    )

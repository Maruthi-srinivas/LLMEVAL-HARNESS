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

    payload = []
    for case in cases:
        item = {
            "context": case.context,
            "expected_output": case.expected_output,
            "id": case.case_key,
            "input": case.input_text,
            "json_schema": case.json_schema,
            "tags": list(case.tags),
        }
        if case.citations:
            item["citations"] = list(case.citations)
        if case.relevant_document_ids:
            item["relevant_document_ids"] = list(case.relevant_document_ids)
        if case.retrieved_context is not None:
            item["retrieved_context"] = list(case.retrieved_context)
        if case.expected_policy is not None:
            item["expected_policy"] = case.expected_policy
        if case.human_labels:
            item["human_labels"] = case.human_labels
        if case.allowed_tools:
            item["allowed_tools"] = list(case.allowed_tools)
        if case.goal:
            item["goal"] = case.goal
        if case.constraints:
            item["constraints"] = list(case.constraints)
        if case.expected_tools:
            item["expected_tools"] = list(case.expected_tools)
        payload.append(item)
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

    retrieved_context, retrieved_errors = _documents(payload.get("retrieved_context"), line_number, "retrieved_context")
    relevant_ids, relevant_errors = _string_list(
        payload.get("relevant_document_ids", []), line_number, "relevant_document_ids"
    )
    citations, citation_errors = _citations(payload.get("citations", []), line_number)
    expected_policy, policy_errors = _policy(payload.get("expected_policy"), line_number)
    human_labels, label_errors = _human_labels(payload.get("human_labels"), line_number)
    allowed_tools, allowed_errors = _string_list(payload.get("allowed_tools", []), line_number, "allowed_tools")
    goal, goal_errors = _optional_text(payload.get("goal"), line_number, "goal")
    constraints, constraint_errors = _string_list(payload.get("constraints", []), line_number, "constraints")
    expected_tools, tool_errors = _expected_tools(payload.get("expected_tools"), line_number)
    errors.extend(retrieved_errors)
    errors.extend(relevant_errors)
    errors.extend(citation_errors)
    errors.extend(policy_errors)
    errors.extend(label_errors)
    errors.extend(allowed_errors)
    errors.extend(goal_errors)
    errors.extend(constraint_errors)
    errors.extend(tool_errors)

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
            retrieved_context=None if "retrieved_context" not in payload else tuple(retrieved_context),
            relevant_document_ids=tuple(relevant_ids),
            citations=tuple(citations),
            expected_policy=expected_policy,
            human_labels=human_labels,
            allowed_tools=tuple(allowed_tools),
            goal=goal,
            constraints=tuple(constraints),
            expected_tools=tuple(expected_tools),
            line_number=line_number,
        ),
        [],
    )


def _documents(value: Any, line_number: int, field: str) -> tuple[list[dict[str, str]], list[str]]:
    if value is None:
        return [], []
    if not isinstance(value, list):
        return [], [f"Line {line_number}: {field} must be a list of documents"]
    documents = []
    errors = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("text"), str):
            errors.append(f"Line {line_number}: {field} entries require string id and text")
            continue
        if item["id"] == "" or item["text"] == "":
            errors.append(f"Line {line_number}: {field} entries require string id and text")
            continue
        documents.append({"id": item["id"], "text": item["text"]})
    return documents, errors


def _string_list(value: Any, line_number: int, field: str) -> tuple[list[str], list[str]]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item != "" for item in value):
        return [], [f"Line {line_number}: {field} must be a list of strings"]
    return list(value), []


def _citations(value: Any, line_number: int) -> tuple[list[dict[str, str]], list[str]]:
    if not isinstance(value, list):
        return [], [f"Line {line_number}: citations must be a list"]
    citations = []
    errors = []
    for item in value:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("document_id"), str)
            or not isinstance(item.get("claim"), str)
            or item["document_id"] == ""
            or item["claim"] == ""
        ):
            errors.append(f"Line {line_number}: citations require string document_id and claim")
            continue
        citations.append({"document_id": item["document_id"], "claim": item["claim"]})
    return citations, errors


_LABELS = {"passed", "failed", "metric_error"}


def _optional_text(value: Any, line_number: int, field: str) -> tuple[str | None, list[str]]:
    if value is None:
        return None, []
    if not isinstance(value, str):
        return None, [f"Line {line_number}: {field} must be a string"]
    return value or None, []


def _expected_tools(value: Any, line_number: int) -> tuple[list[dict], list[str]]:
    if value is None:
        return [], []
    if not isinstance(value, list):
        return [], [f"Line {line_number}: expected_tools must be a list"]
    tools = []
    errors = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or item["name"] == "":
            errors.append(f"Line {line_number}: expected_tools entries require a name")
            continue
        arguments = item.get("arguments", {})
        if not isinstance(arguments, dict):
            errors.append(f"Line {line_number}: expected_tools arguments must be an object")
            continue
        tools.append({"name": item["name"], "arguments": arguments})
    return tools, errors


def _policy(value: Any, line_number: int) -> tuple[str | None, list[str]]:
    if value is None:
        return None, []
    if value not in {"refuse", "answer"}:
        return None, [f"Line {line_number}: expected_policy must be refuse or answer"]
    return value, []


def _human_labels(value: Any, line_number: int) -> tuple[dict[str, str] | None, list[str]]:
    if value is None:
        return None, []
    if not isinstance(value, dict) or not value:
        return None, [f"Line {line_number}: human_labels must be an object"]
    labels: dict[str, str] = {}
    errors: list[str] = []
    for key, label in value.items():
        if not isinstance(key, str) or key == "" or label not in _LABELS:
            errors.append(f"Line {line_number}: human_labels values must be passed, failed, or metric_error")
            continue
        labels[key] = label
    return labels, errors

import pytest

from evaluator.datasets.loader import DatasetValidationError, load_jsonl


def _write(tmp_path, lines: list[str]):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_loader_reports_line_numbers_for_malformed_missing_and_duplicate_records(tmp_path):
    path = _write(
        tmp_path,
        [
            '{"id":"ok","input":"q","expected_output":"a"}',
            "{",
            '{"id":"missing","input":"q"}',
            '{"id":"ok","input":"q2","expected_output":"b"}',
        ],
    )
    with pytest.raises(DatasetValidationError) as caught:
        load_jsonl(path)
    text = "\n".join(caught.value.errors)
    assert "Line 2" in text
    assert "malformed JSON" in text
    assert "Line 3" in text
    assert "expected_output" in text
    assert "Line 4" in text
    assert "duplicate id" in text


def test_loader_rejects_empty_files_and_oversized_files(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n\n", encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="no records"):
        load_jsonl(empty)

    big = tmp_path / "big.jsonl"
    big.write_bytes(b"x" * 32)
    with pytest.raises(DatasetValidationError, match="exceeds"):
        load_jsonl(big, max_bytes=16)


def test_loader_normalizes_optional_fields(tmp_path):
    path = _write(
        tmp_path,
        [
            '{"id":"qa","input":"q","expected_output":"a","tags":["support"],"context":"docs","json_schema":{"type":"object"}}',
        ],
    )
    cases = load_jsonl(path)
    assert cases[0].case_key == "qa"
    assert cases[0].tags == ("support",)
    assert cases[0].context == "docs"
    assert cases[0].json_schema == {"type": "object"}
    assert cases[0].line_number == 1


def test_loader_rejects_bad_tags(tmp_path):
    path = _write(tmp_path, ['{"id":"qa","input":"q","expected_output":"a","tags":"support"}'])
    with pytest.raises(DatasetValidationError, match="Line 1: tags"):
        load_jsonl(path)

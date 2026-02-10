from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import jsonschema

from ..errors import ExecFailureError


def _repo_root() -> Path:
    # killer_7/validate/review_json.py -> repo_root/killer_7/validate/review_json.py
    return Path(__file__).resolve().parents[2]


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExecFailureError(f"Failed to read JSON schema: {str(path)!r}") from exc

    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise ExecFailureError(f"Invalid JSON schema: {str(path)!r}: {exc}") from exc

    if not isinstance(data, dict):
        raise ExecFailureError(
            f"Invalid JSON schema: {str(path)!r}: root must be object"
        )
    return data


def _format_path(error: jsonschema.ValidationError) -> str:
    if not error.path:
        return "$"
    parts = []
    for p in error.path:
        if isinstance(p, int):
            parts.append(f"[{p}]")
        else:
            parts.append("." + str(p))
    return "$" + "".join(parts)


def _validate_line_range_semantics(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return errors

    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            continue
        code_location = f.get("code_location")
        if not isinstance(code_location, dict):
            continue
        line_range = code_location.get("line_range")
        if not isinstance(line_range, dict):
            continue
        start = line_range.get("start")
        end = line_range.get("end")
        if isinstance(start, int) and isinstance(end, int) and end < start:
            errors.append(
                f"findings[{i}].code_location.line_range.end must be >= start"
            )
    return errors


def validate_aspect_review_json(
    payload: object, *, expected_scope_id: Optional[str]
) -> None:
    if not isinstance(payload, dict):
        raise ExecFailureError("Review JSON must be an object")

    schema_path = _repo_root() / "schemas" / "aspect-review.schema.json"
    schema = _load_schema(schema_path)

    scope_id = payload.get("scope_id")
    if expected_scope_id is not None:
        if not isinstance(scope_id, str) or scope_id != expected_scope_id:
            raise ExecFailureError(
                f"scope_id mismatch: expected {expected_scope_id}, got {scope_id}"
            )

    try:
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
        validator = validator_cls(schema)
    except Exception as exc:  # noqa: BLE001
        raise ExecFailureError(f"Invalid JSON schema: {schema_path}: {exc}") from exc

    schema_errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if schema_errors:
        rendered = "; ".join(
            f"{_format_path(e)}: {e.message}" for e in schema_errors[:8]
        )
        more = "" if len(schema_errors) <= 8 else f" (+{len(schema_errors) - 8} more)"
        raise ExecFailureError(f"Review JSON validation failed: {rendered}{more}")

    semantic_errors = _validate_line_range_semantics(payload)
    if semantic_errors:
        joined = "; ".join(semantic_errors[:8])
        more = (
            "" if len(semantic_errors) <= 8 else f" (+{len(semantic_errors) - 8} more)"
        )
        raise ExecFailureError(f"Review JSON validation failed: {joined}{more}")

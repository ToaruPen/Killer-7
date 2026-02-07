from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..artifacts import atomic_write_json_secure, ensure_artifacts_dir
from ..errors import ExecFailureError
from ..llm.opencode_runner import OpenCodeRunner


_ASPECT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

_ALLOWED_STATUS = {
    "Approved",
    "Approved with nits",
    "Blocked",
    "Question",
}

_PRIORITY_ALLOWED = {"P0", "P1", "P2", "P3"}


@dataclass(frozen=True)
class PromptInputs:
    aspect: str
    scope_id: str
    context_bundle: str
    sot: str = ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExecFailureError(
            f"Failed to read prompt template: {str(path)!r}"
        ) from exc


def _render_prompt(
    *,
    base_template: str,
    aspect_template: str,
    inputs: PromptInputs,
) -> str:
    # Keep templating deliberately simple and single-pass to avoid rewriting
    # placeholder-like strings inside inserted context.
    replacements = {
        "ASPECT_NAME": inputs.aspect,
        "SCOPE_ID": inputs.scope_id,
        "CONTEXT_BUNDLE": inputs.context_bundle,
        "SOT": inputs.sot,
        "ASPECT_PROMPT": aspect_template,
    }
    pat = re.compile(r"\{\{(ASPECT_NAME|SCOPE_ID|CONTEXT_BUNDLE|SOT|ASPECT_PROMPT)\}\}")

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        return replacements.get(key, m.group(0))

    return pat.sub(repl, base_template)


class ViewpointRunner(Protocol):
    def run_viewpoint(
        self,
        *,
        out_dir: str,
        viewpoint: str,
        message: str,
        timeout_s: int | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, object]: ...


def _validate_schema_v3_required_keys(
    payload: object, *, expected_scope_id: str
) -> None:
    if not isinstance(payload, dict):
        raise ExecFailureError("Review JSON must be an object")

    errors = _validate_review_json(payload, expected_scope_id=expected_scope_id)
    if errors:
        joined = "; ".join(errors[:8])
        more = "" if len(errors) <= 8 else f" (+{len(errors) - 8} more)"
        raise ExecFailureError(f"Review JSON validation failed: {joined}{more}")


def _is_repo_relative_path(path: str) -> bool:
    if not path:
        return False
    if path.startswith("/"):
        return False
    if path in {".", ".."}:
        return False
    parts = [p for p in path.split("/") if p]
    return ".." not in parts


def _validate_review_json(
    obj: dict[str, object], *, expected_scope_id: str
) -> list[str]:
    # Keep this aligned with scripts/validate-review-json.py.
    errors: list[str] = []

    required = {
        "schema_version",
        "scope_id",
        "status",
        "findings",
        "questions",
        "overall_explanation",
    }

    missing = required - set(obj.keys())
    if missing:
        errors.append(f"missing keys: {sorted(missing)}")
        return errors

    extra = set(obj.keys()) - required
    if extra:
        errors.append(f"unexpected keys: {sorted(extra)}")

    if obj.get("schema_version") != 3:
        errors.append("schema_version must be 3")

    scope_id = obj.get("scope_id")
    if not isinstance(scope_id, str) or not scope_id:
        errors.append("scope_id must be a non-empty string")
    elif scope_id != expected_scope_id:
        errors.append(
            f"scope_id mismatch: expected {expected_scope_id}, got {scope_id}"
        )

    status = obj.get("status")
    if status not in _ALLOWED_STATUS:
        errors.append(f"status must be one of {sorted(_ALLOWED_STATUS)}")

    findings = obj.get("findings")
    if not isinstance(findings, list):
        errors.append("findings must be an array")
        findings = []

    questions = obj.get("questions")
    if not isinstance(questions, list) or any(
        not isinstance(x, str) for x in questions
    ):
        errors.append("questions must be an array of strings")
        questions = []

    overall_explanation = obj.get("overall_explanation")
    if not isinstance(overall_explanation, str) or not overall_explanation:
        errors.append("overall_explanation must be a non-empty string")

    for idx, item in enumerate(findings):
        if not isinstance(item, dict):
            errors.append(f"findings[{idx}] is not an object")
            continue

        required_finding_keys = {"title", "body", "priority", "code_location"}
        for k in sorted(required_finding_keys):
            if k not in item:
                errors.append(f"findings[{idx}] missing key: {k}")
        extra_finding = set(item.keys()) - required_finding_keys
        if extra_finding:
            errors.append(f"findings[{idx}] unexpected keys: {sorted(extra_finding)}")

        title = item.get("title")
        if not isinstance(title, str) or not title:
            errors.append(f"findings[{idx}].title must be a non-empty string")
        elif len(title) > 120:
            errors.append(f"findings[{idx}].title must be <= 120 chars")

        body = item.get("body")
        if not isinstance(body, str) or not body:
            errors.append(f"findings[{idx}].body must be a non-empty string")

        priority = item.get("priority")
        if not isinstance(priority, str) or priority not in _PRIORITY_ALLOWED:
            errors.append(
                f"findings[{idx}].priority must be one of {sorted(_PRIORITY_ALLOWED)}"
            )

        code_location = item.get("code_location")
        if not isinstance(code_location, dict):
            errors.append(f"findings[{idx}].code_location must be an object")
            continue

        required_code_location_keys = {"repo_relative_path", "line_range"}
        missing_code_location = required_code_location_keys - set(code_location.keys())
        if missing_code_location:
            errors.append(
                f"findings[{idx}].code_location missing keys: {sorted(missing_code_location)}"
            )
        extra_code_location = set(code_location.keys()) - required_code_location_keys
        if extra_code_location:
            errors.append(
                f"findings[{idx}].code_location unexpected keys: {sorted(extra_code_location)}"
            )

        repo_relative_path = code_location.get("repo_relative_path")
        if not isinstance(repo_relative_path, str) or not _is_repo_relative_path(
            repo_relative_path
        ):
            errors.append(
                f"findings[{idx}].code_location.repo_relative_path must be repo-relative (no '..', not absolute)"
            )

        line_range = code_location.get("line_range")
        if not isinstance(line_range, dict):
            errors.append(f"findings[{idx}].code_location.line_range must be an object")
            continue

        required_line_range_keys = {"start", "end"}
        missing_line_range = required_line_range_keys - set(line_range.keys())
        if missing_line_range:
            errors.append(
                f"findings[{idx}].code_location.line_range missing keys: {sorted(missing_line_range)}"
            )
        extra_line_range = set(line_range.keys()) - required_line_range_keys
        if extra_line_range:
            errors.append(
                f"findings[{idx}].code_location.line_range unexpected keys: {sorted(extra_line_range)}"
            )

        start = line_range.get("start")
        end = line_range.get("end")
        if not isinstance(start, int) or start < 1:
            errors.append(
                f"findings[{idx}].code_location.line_range.start must be int >= 1"
            )
        if not isinstance(end, int) or end < 1:
            errors.append(
                f"findings[{idx}].code_location.line_range.end must be int >= 1"
            )
        if isinstance(start, int) and isinstance(end, int) and end < start:
            errors.append(
                f"findings[{idx}].code_location.line_range.end must be >= start"
            )

    # Cross-field constraints
    if status == "Approved":
        if len(findings) != 0:
            errors.append("Approved must have findings=[]")
        if len(questions) != 0:
            errors.append("Approved must have questions=[]")

    if status == "Approved with nits":
        blocking = [
            f
            for f in findings
            if isinstance(f, dict) and f.get("priority") in ("P0", "P1")
        ]
        if blocking:
            errors.append("Approved with nits must not include P0/P1 findings")
        if len(questions) != 0:
            errors.append("Approved with nits must have questions=[]")

    if status == "Blocked":
        blocking = [
            f
            for f in findings
            if isinstance(f, dict) and f.get("priority") in ("P0", "P1")
        ]
        if not blocking:
            errors.append("Blocked must include at least one P0/P1 finding")

    if status == "Question":
        if len(questions) == 0:
            errors.append("Question must include at least one question")

    return errors


def run_one_aspect(
    *,
    base_dir: str,
    aspect: str,
    scope_id: str,
    context_bundle: str,
    sot: str = "",
    runner: ViewpointRunner | None = None,
    timeout_s: int | None = None,
    prompts_dir: str | None = None,
) -> dict[str, object]:
    """Run a single aspect via OpenCode and write `.ai-review/aspects/<aspect>.json`.

    This function is intentionally small and file-based; orchestration/parallelization is
    handled by higher-level issues (e.g. #8).
    """

    a = (aspect or "").strip().lower()
    a = a.replace("_", "-")
    if not a or not _ASPECT_RE.match(a):
        raise ExecFailureError(f"Invalid aspect: {aspect!r}")
    if not isinstance(scope_id, str) or not scope_id.strip():
        raise ExecFailureError("scope_id is required")

    if not isinstance(context_bundle, str):
        raise ExecFailureError("context_bundle must be a string")
    if not isinstance(sot, str):
        raise ExecFailureError("sot must be a string")

    scope_id = scope_id.strip()

    # Default to repo-relative prompts/ to avoid CWD dependency.
    prompt_root = (
        Path(prompts_dir)
        if prompts_dir
        else (Path(__file__).resolve().parents[2] / "prompts")
    )
    base_path = prompt_root / "base-review.md"
    aspect_path = prompt_root / "aspects" / f"{a}.md"

    base_template = _read_text(base_path)
    aspect_template = _read_text(aspect_path)
    prompt = _render_prompt(
        base_template=base_template,
        aspect_template=aspect_template,
        inputs=PromptInputs(
            aspect=a, scope_id=scope_id, context_bundle=context_bundle, sot=sot
        ),
    )

    out_dir = ensure_artifacts_dir(base_dir)
    r = runner or OpenCodeRunner.from_env()
    res = r.run_viewpoint(
        out_dir=out_dir,
        viewpoint=a,
        message=prompt,
        timeout_s=timeout_s,
    )

    payload = res.get("payload")
    _validate_schema_v3_required_keys(payload, expected_scope_id=scope_id)

    aspect_result_path = os.path.join(out_dir, "aspects", f"{a}.json")
    atomic_write_json_secure(aspect_result_path, payload)

    return {
        "aspect": a,
        "scope_id": scope_id,
        "aspect_result_path": aspect_result_path,
        "opencode_result_path": res.get("result_path"),
        "payload": payload,
    }

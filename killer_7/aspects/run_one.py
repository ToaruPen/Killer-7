from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..artifacts import (
    atomic_write_json_secure,
    ensure_artifacts_dir,
    write_validation_error_json,
)
from ..errors import ExecFailureError
from ..llm.opencode_runner import OpenCodeRunner
from ..aspect_id import normalize_aspect
from ..validate.review_json import validate_aspect_review_json


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
    runner_env: dict[str, str] | None = None,
) -> dict[str, object]:
    """Run a single aspect via OpenCode and write `.ai-review/aspects/<aspect>.json`.

    This function is intentionally small and file-based; orchestration/parallelization is
    handled by higher-level issues (e.g. #8).
    """

    a = normalize_aspect(aspect)
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

    repo_ro = ""
    allowlist_text = ""
    runner_env_effective = dict(runner_env) if runner_env else None
    if runner_env_effective:
        repo_ro = (runner_env_effective.get("KILLER7_REPO_READONLY") or "").strip()
        allowlist_text = (
            runner_env_effective.get("KILLER7_REPO_ALLOWLIST") or ""
        ).strip()
        if repo_ro == "1" and not allowlist_text:
            runner_env_effective["KILLER7_REPO_READONLY"] = "0"
            runner_env_effective.pop("KILLER7_REPO_ALLOWLIST", None)
            repo_ro = "0"
    if repo_ro == "1":
        prompt += "\n\n## Hybrid Access Policy\n"
        prompt += "- Repository read-only access is allowed for this aspect.\n"
        prompt += "- You MUST limit repository access to these allowlist paths:\n"
        for line in allowlist_text.splitlines():
            p = line.strip()
            if p:
                prompt += f"  - {p}\n"

    out_dir = ensure_artifacts_dir(base_dir)
    r = runner or OpenCodeRunner.from_env()
    res = r.run_viewpoint(
        out_dir=out_dir,
        viewpoint=a,
        message=prompt,
        timeout_s=timeout_s,
        env=runner_env_effective,
    )

    payload = res.get("payload")

    aspect_result_path = os.path.join(out_dir, "aspects", f"{a}.json")
    rel_target = os.path.relpath(aspect_result_path, base_dir)
    # Keep artifact paths stable and machine-friendly across OSes.
    rel_target = rel_target.replace(os.sep, "/")
    try:
        validate_aspect_review_json(payload, expected_scope_id=scope_id)
    except ExecFailureError as exc:
        msg = str(exc)
        errors = [msg]
        prefix = "Review JSON validation failed: "
        if msg.startswith(prefix):
            # Preserve multiple schema errors as a list when available.
            rest = msg[len(prefix) :]
            parts = [p.strip() for p in rest.split(";") if p.strip()]
            if parts:
                errors = parts

        # Leave a machine-readable error artifact for downstream gates.
        write_validation_error_json(
            out_dir,
            filename=f"{a}.schema.error.json",
            kind="schema_validation_failed",
            message=msg,
            target_path=rel_target,
            errors=errors,
            extra={"aspect": a, "scope_id": scope_id},
        )
        raise

    atomic_write_json_secure(aspect_result_path, payload)

    return {
        "aspect": a,
        "scope_id": scope_id,
        "aspect_result_path": aspect_result_path,
        "opencode_result_path": res.get("result_path"),
        "payload": payload,
    }

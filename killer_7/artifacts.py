"""Artifacts writer.

All artifacts are written under `./.ai-review/`.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone

from .aspect_id import normalize_aspect
from .github.pr_input import ChangedFile, PrInput


def now_utc_z() -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def ensure_artifacts_dir(base_dir: str) -> str:
    out_dir = os.path.join(base_dir, ".ai-review")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def _atomic_write_text(path: str, content: str) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
        if not content.endswith("\n"):
            fh.write("\n")
    os.replace(tmp, path)


def _atomic_write_json(path: str, payload: object) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        fh.write("\n")
    os.replace(tmp, path)


def atomic_write_json_secure(
    path: str,
    payload: object,
    *,
    dir_mode: int = 0o700,
    file_mode: int = 0o600,
) -> None:
    """Atomically write JSON and restrict permissions.

    This helper is intended for artifacts that may contain sensitive content.
    """

    dir_name = os.path.dirname(path) or "."
    base = os.path.basename(path)
    if dir_name != ".":
        os.makedirs(dir_name, mode=dir_mode, exist_ok=True)
        try:
            os.chmod(dir_name, dir_mode)
        except OSError:
            pass

    tmp = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=dir_name,
            prefix=f".{base}.tmp.",
        ) as fh:
            tmp = fh.name
            fh.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            fh.write("\n")

        try:
            os.chmod(tmp, file_mode)
        except OSError:
            pass

        os.replace(tmp, path)
        tmp = ""
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def atomic_write_text_secure(
    path: str,
    content: str,
    *,
    dir_mode: int = 0o700,
    file_mode: int = 0o600,
) -> None:
    dir_name = os.path.dirname(path) or "."
    base = os.path.basename(path)
    if dir_name != ".":
        os.makedirs(dir_name, mode=dir_mode, exist_ok=True)
        try:
            os.chmod(dir_name, dir_mode)
        except OSError:
            pass

    tmp = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=dir_name,
            prefix=f".{base}.tmp.",
        ) as fh:
            tmp = fh.name
            fh.write(content)
            if content and (not content.endswith("\n")):
                fh.write("\n")

        try:
            os.chmod(tmp, file_mode)
        except OSError:
            pass

        os.replace(tmp, path)
        tmp = ""
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def write_diff_patch(out_dir: str, patch: str) -> str:
    path = os.path.join(out_dir, "diff.patch")
    _atomic_write_text(path, patch)
    return path


def _changed_files_tsv(files: list[ChangedFile]) -> str:
    lines = ["path\tstatus\tprevious_path\tadditions\tdeletions"]
    for f in files:
        prev = f.previous_path or ""
        lines.append(f"{f.path}\t{f.status}\t{prev}\t{f.additions}\t{f.deletions}")
    return "\n".join(lines) + "\n"


def write_changed_files_tsv(out_dir: str, files: list[ChangedFile]) -> str:
    path = os.path.join(out_dir, "changed-files.tsv")
    _atomic_write_text(path, _changed_files_tsv(files).rstrip("\n"))
    return path


def write_meta_json(out_dir: str, pr_input: PrInput) -> str:
    path = os.path.join(out_dir, "meta.json")
    payload = {
        "schema_version": 1,
        "repo": pr_input.repo,
        "pr": pr_input.pr,
        "head_sha": pr_input.head_sha,
        "diff_mode": pr_input.diff_mode,
        "base_head_sha": pr_input.base_head_sha,
        "fetched_at": now_utc_z(),
        "changed_files_count": len(pr_input.changed_files),
    }
    _atomic_write_json(path, payload)
    return path


def write_pr_input_artifacts(out_dir: str, pr_input: PrInput) -> dict[str, str]:
    return {
        "diff_patch": write_diff_patch(out_dir, pr_input.diff_patch),
        "changed_files_tsv": write_changed_files_tsv(out_dir, pr_input.changed_files),
        "meta_json": write_meta_json(out_dir, pr_input),
    }


def write_sot_md(out_dir: str, content: str) -> str:
    path = os.path.join(out_dir, "sot.md")
    _atomic_write_text(path, (content or "").rstrip("\n"))
    return path


def write_context_bundle_txt(out_dir: str, content: str) -> str:
    path = os.path.join(out_dir, "context-bundle.txt")
    _atomic_write_text(path, (content or "").rstrip("\n"))
    return path


def write_tool_trace_jsonl(out_dir: str, content: str) -> str:
    path = os.path.join(out_dir, "tool-trace.jsonl")
    atomic_write_text_secure(path, (content or "").rstrip("\n"))
    return path


def write_tool_bundle_txt(out_dir: str, content: str) -> str:
    path = os.path.join(out_dir, "tool-bundle.txt")
    atomic_write_text_secure(path, (content or "").rstrip("\n"))
    return path


def write_evidence_json(out_dir: str, payload: object) -> str:
    path = os.path.join(out_dir, "evidence.json")
    atomic_write_json_secure(path, payload)
    return path


def write_aspect_evidence_json(out_dir: str, *, aspect: str, payload: object) -> str:
    a = normalize_aspect(aspect)
    aspects_dir = os.path.join(out_dir, "aspects")
    os.makedirs(aspects_dir, mode=0o700, exist_ok=True)
    path = os.path.join(aspects_dir, f"{a}.evidence.json")
    atomic_write_json_secure(path, payload)
    return path


def write_aspect_policy_json(out_dir: str, *, aspect: str, payload: object) -> str:
    a = normalize_aspect(aspect)
    aspects_dir = os.path.join(out_dir, "aspects")
    os.makedirs(aspects_dir, mode=0o700, exist_ok=True)
    path = os.path.join(aspects_dir, f"{a}.policy.json")
    atomic_write_json_secure(path, payload)
    return path


def write_aspects_policy_index_json(out_dir: str, payload: object) -> str:
    aspects_dir = os.path.join(out_dir, "aspects")
    os.makedirs(aspects_dir, mode=0o700, exist_ok=True)
    path = os.path.join(aspects_dir, "index.policy.json")
    atomic_write_json_secure(path, payload)
    return path


def write_aspects_evidence_index_json(out_dir: str, payload: object) -> str:
    aspects_dir = os.path.join(out_dir, "aspects")
    os.makedirs(aspects_dir, mode=0o700, exist_ok=True)
    path = os.path.join(aspects_dir, "index.evidence.json")
    atomic_write_json_secure(path, payload)
    return path


def write_warnings_txt(out_dir: str, warnings: list[str]) -> str:
    path = os.path.join(out_dir, "warnings.txt")
    lines = [str(x) for x in warnings if str(x).strip()]
    _atomic_write_text(path, "\n".join(lines))
    return path


def write_allowlist_paths_json(out_dir: str, paths: list[str]) -> str:
    path = os.path.join(out_dir, "allowlist-paths.json")
    stable_paths = sorted(set(paths))
    payload = {
        "schema_version": 1,
        "generated_at": now_utc_z(),
        "paths": stable_paths,
    }
    _atomic_write_json(path, payload)
    return path


def write_validation_error_json(
    out_dir: str,
    *,
    filename: str | None,
    kind: str,
    message: str,
    target_path: str,
    errors: list[str] | None = None,
    extra: dict[str, object] | None = None,
) -> str:
    """Write a schema/validation error artifact under `.ai-review/errors/`.

    The output is intended to be machine-readable and stable.
    """

    errors_dir = os.path.join(out_dir, "errors")

    # Guard against path traversal. Treat `filename` as a name, not a path.
    raw_name = "" if filename is None else str(filename)
    normalized = raw_name.replace("\\", "/")
    safe_name = os.path.basename(normalized)
    if not safe_name or safe_name in {".", ".."}:
        safe_name = "validation-error.json"

    path = os.path.join(errors_dir, safe_name)

    # Defense-in-depth: ensure the final path stays within errors_dir.
    errors_dir_real = os.path.realpath(errors_dir)
    path_real = os.path.realpath(path)
    if not (
        path_real == errors_dir_real or path_real.startswith(errors_dir_real + os.sep)
    ):
        # If we can't guarantee containment, fail closed.
        raise ValueError("Invalid filename: must not escape errors dir")

    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": str(kind or ""),
        "message": str(message or ""),
        "target_path": str(target_path or ""),
        "errors": list(errors or []),
    }
    if safe_name != raw_name:
        payload["original_filename"] = raw_name
    if extra:
        for k, v in extra.items():
            if k not in payload:
                try:
                    json.dumps(v)
                    payload[str(k)] = v
                except Exception:  # noqa: BLE001
                    payload[str(k)] = "" if v is None else str(v)

    atomic_write_json_secure(path, payload)
    return path


def write_content_warnings_json(out_dir: str, warnings: list[object]) -> str:
    """Write content warnings as JSON.

    The caller can pass either:
    - ContentWarning dataclasses (from killer_7.github.content)
    - Mapping objects (e.g. dict) with matching keys
    """

    path = os.path.join(out_dir, "content-warnings.json")

    items = [_warning_to_json_dict(w) for w in warnings]

    payload = {
        "schema_version": 1,
        "generated_at": now_utc_z(),
        "warnings": items,
    }
    _atomic_write_json(path, payload)
    return path


def write_review_summary_json(out_dir: str, payload: object) -> str:
    path = os.path.join(out_dir, "review-summary.json")
    atomic_write_json_secure(path, payload)
    return path


def write_review_summary_md(out_dir: str, content: str) -> str:
    path = os.path.join(out_dir, "review-summary.md")
    _atomic_write_text(path, (content or "").rstrip("\n"))
    return path


def _warning_to_json_dict(w: object) -> dict[str, object]:
    if isinstance(w, Mapping):
        kind = w.get("kind", "")
        p = w.get("path", "")
        msg = w.get("message", "")
        size = w.get("size_bytes", None)
        limit = w.get("limit_bytes", None)
    else:
        kind = getattr(w, "kind", "")
        p = getattr(w, "path", "")
        msg = getattr(w, "message", "")
        size = getattr(w, "size_bytes", None)
        limit = getattr(w, "limit_bytes", None)

    return {
        "kind": "" if kind is None else str(kind),
        "path": "" if p is None else str(p),
        "message": "" if msg is None else str(msg),
        "size_bytes": size if isinstance(size, int) else None,
        "limit_bytes": limit if isinstance(limit, int) else None,
    }

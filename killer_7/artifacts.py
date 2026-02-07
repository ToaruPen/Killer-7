"""Artifacts writer.

All artifacts are written under `./.ai-review/`.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
import tempfile
from datetime import datetime, timezone

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

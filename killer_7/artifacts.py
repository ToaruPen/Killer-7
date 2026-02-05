"""Artifacts writer.

All artifacts are written under `./.ai-review/`.
"""

from __future__ import annotations

import json
import os
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

"""PR input fetcher (diff + metadata).

Fetches PR diff patch, changed files list, and HEAD SHA via `gh`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ExecFailureError
from .gh import GhClient


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    previous_path: str | None
    additions: int
    deletions: int


@dataclass(frozen=True)
class PrInput:
    repo: str
    pr: int
    head_sha: str
    diff_patch: str
    changed_files: list[ChangedFile]
    diff_mode: str = "full"
    base_head_sha: str = ""


def _to_int(value: Any, *, field: str) -> int:
    try:
        return int(value)
    except Exception as exc:  # noqa: BLE001
        raise ExecFailureError(f"Invalid integer for {field}") from exc


def fetch_pr_input(
    *,
    repo: str,
    pr: int,
    gh: GhClient | None = None,
    base_head_sha: str = "",
) -> PrInput:
    client = gh or GhClient.from_env()

    head_sha = client.pr_head_ref_oid(repo=repo, pr=pr)
    requested_base_sha = (base_head_sha or "").strip()
    base_sha = ""
    diff_mode = "full"
    if requested_base_sha and requested_base_sha != head_sha:
        base_sha = requested_base_sha
        diff_patch = client.pr_compare_diff_patch(
            repo=repo, base=base_sha, head=head_sha
        )
        diff_mode = "incremental"
    else:
        diff_patch = client.pr_diff_patch(repo=repo, pr=pr)
    raw_files = client.pr_files(repo=repo, pr=pr)
    latest_head_sha = client.pr_head_ref_oid(repo=repo, pr=pr)

    if latest_head_sha != head_sha:
        raise ExecFailureError(
            "PR head changed during input fetch; retry review on latest head"
        )

    changed_files: list[ChangedFile] = []
    for item in raw_files:
        path = (item.get("filename") or "").strip()
        status = (item.get("status") or "").strip()
        prev = (item.get("previous_filename") or "").strip() or None
        additions = _to_int(item.get("additions", 0), field="additions")
        deletions = _to_int(item.get("deletions", 0), field="deletions")

        if not path or not status:
            raise ExecFailureError("Missing filename/status in PR files metadata")

        previous_path = prev if status == "renamed" else None

        changed_files.append(
            ChangedFile(
                path=path,
                status=status,
                previous_path=previous_path,
                additions=additions,
                deletions=deletions,
            )
        )

    return PrInput(
        repo=repo,
        pr=pr,
        head_sha=head_sha,
        diff_patch=diff_patch,
        changed_files=changed_files,
        diff_mode=diff_mode,
        base_head_sha=base_sha,
    )

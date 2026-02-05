"""GitHub CLI (`gh`) wrapper.

This module provides a thin wrapper around `gh` subprocess execution.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from ..errors import BlockedError, ExecFailureError


def _gh_bin() -> str:
    return os.environ.get("KILLER7_GH_BIN", "gh")


def _is_auth_blocked(stderr: str) -> bool:
    s = stderr.lower()
    return (
        "gh auth login" in s
        or "not logged into any github hosts" in s
        or "authentication" in s
        or "oauth" in s
        or "requires authentication" in s
    )


def _truncate(s: str, max_chars: int = 2000) -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "... [truncated]"


@dataclass(frozen=True)
class GhClient:
    """Minimal `gh` client used by Killer-7."""

    bin_path: str = "gh"
    timeout_s: int = 60

    @classmethod
    def from_env(cls) -> "GhClient":
        return cls(bin_path=_gh_bin())

    def _run(self, args: list[str]) -> str:
        try:
            p = subprocess.run(
                [self.bin_path, *args],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=self.timeout_s,
            )
        except FileNotFoundError as exc:
            raise BlockedError(
                "`gh` is required. Install GitHub CLI and ensure it is on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ExecFailureError(f"`gh` timed out after {self.timeout_s}s") from exc

        if p.returncode != 0:
            stderr = (p.stderr or "").strip()
            msg = stderr or f"`gh` failed (exit={p.returncode})"
            msg = _truncate(msg)
            if _is_auth_blocked(stderr):
                raise BlockedError(msg)
            raise ExecFailureError(msg)

        return p.stdout

    def pr_diff_patch(self, *, repo: str, pr: int) -> str:
        return self._run(["pr", "diff", str(pr), "--repo", repo, "--patch"])

    def pr_head_ref_oid(self, *, repo: str, pr: int) -> str:
        raw = self._run(["pr", "view", str(pr), "--repo", repo, "--json", "headRefOid"])
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ExecFailureError("`gh pr view` returned invalid JSON") from exc
        head = (data.get("headRefOid") or "").strip()
        if not head:
            raise ExecFailureError("Missing headRefOid in `gh pr view` output")
        return head

    def pr_files(self, *, repo: str, pr: int) -> list[dict[str, Any]]:
        endpoint = f"repos/{repo}/pulls/{pr}/files"
        raw = self._run(["api", "--paginate", "--slurp", endpoint])
        try:
            pages = json.loads(raw or "[]")
        except json.JSONDecodeError as exc:
            raise ExecFailureError("`gh api` returned invalid JSON") from exc

        if isinstance(pages, list) and (not pages or isinstance(pages[0], list)):
            items: list[dict[str, Any]] = []
            for page in pages:
                if isinstance(page, list):
                    for x in page:
                        if isinstance(x, dict):
                            items.append(x)
            return items

        if isinstance(pages, list):
            return [x for x in pages if isinstance(x, dict)]

        raise ExecFailureError("Unexpected JSON shape from `gh api`")

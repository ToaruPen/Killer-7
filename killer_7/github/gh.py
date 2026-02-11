"""GitHub CLI (`gh`) wrapper.

This module provides a thin wrapper around `gh` subprocess execution.
"""

from __future__ import annotations

import json
import os
import subprocess
from urllib.parse import quote
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

    def viewer_login(self) -> str:
        raw = self._run(["api", "user"])
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ExecFailureError("`gh api user` returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ExecFailureError("Unexpected JSON shape from `gh api user`")
        login_obj = data.get("login")
        login = login_obj.strip() if isinstance(login_obj, str) else ""
        if not login:
            raise ExecFailureError("Missing login in `gh api user` output")
        return login

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

    def api_json(self, *, endpoint: str) -> Any:
        """Call `gh api` and parse JSON output."""

        raw = self._run(["api", endpoint])
        try:
            return json.loads(raw or "null")
        except json.JSONDecodeError as exc:
            raise ExecFailureError("`gh api` returned invalid JSON") from exc

    def issue_comments(self, *, repo: str, issue: int) -> list[dict[str, Any]]:
        endpoint = f"repos/{repo}/issues/{issue}/comments"
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

        raise ExecFailureError("Unexpected JSON shape from issue comments API")

    def create_issue_comment(
        self, *, repo: str, issue: int, body: str
    ) -> dict[str, Any]:
        endpoint = f"repos/{repo}/issues/{issue}/comments"
        raw = self._run(["api", "-X", "POST", endpoint, "-f", f"body={body}"])
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ExecFailureError("`gh api` returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ExecFailureError(
                "Unexpected JSON shape from create issue comment API"
            )
        return data

    def update_issue_comment(
        self, *, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        endpoint = f"repos/{repo}/issues/comments/{comment_id}"
        raw = self._run(["api", "-X", "PATCH", endpoint, "-f", f"body={body}"])
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ExecFailureError("`gh api` returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ExecFailureError(
                "Unexpected JSON shape from update issue comment API"
            )
        return data

    def delete_issue_comment(self, *, repo: str, comment_id: int) -> None:
        endpoint = f"repos/{repo}/issues/comments/{comment_id}"
        self._run(["api", "-X", "DELETE", endpoint])

    def repo_commit_tree_sha(self, *, repo: str, ref: str) -> str:
        endpoint = f"repos/{repo}/commits/{quote(ref, safe='')}"
        data = self.api_json(endpoint=endpoint)
        if not isinstance(data, dict):
            raise ExecFailureError("Unexpected JSON shape from commit API")

        commit = data.get("commit")
        if not isinstance(commit, dict):
            raise ExecFailureError("Missing commit object in commit API output")

        tree = commit.get("tree")
        if not isinstance(tree, dict):
            raise ExecFailureError("Missing commit.tree object in commit API output")

        sha = tree.get("sha")
        tree_sha = (sha or "").strip() if isinstance(sha, str) else ""
        if not tree_sha:
            raise ExecFailureError("Missing commit.tree.sha in commit API output")
        return tree_sha

    def repo_tree_recursive(self, *, repo: str, tree_sha: str) -> list[dict[str, Any]]:
        endpoint = f"repos/{repo}/git/trees/{quote(tree_sha, safe='')}?recursive=1"
        data = self.api_json(endpoint=endpoint)
        if not isinstance(data, dict):
            raise ExecFailureError("Unexpected JSON shape from tree API")
        if data.get("truncated") is True:
            raise ExecFailureError(
                "Tree API response was truncated; cannot safely resolve allowlist from partial tree"
            )
        tree = data.get("tree")
        if not isinstance(tree, list):
            raise ExecFailureError("Missing tree list in tree API output")
        return [x for x in tree if isinstance(x, dict)]

    def repo_contents(self, *, repo: str, path: str, ref: str) -> dict[str, Any]:
        p = quote(path, safe="/")
        r = quote(ref, safe="")
        endpoint = f"repos/{repo}/contents/{p}?ref={r}"
        data = self.api_json(endpoint=endpoint)
        if not isinstance(data, dict):
            raise ExecFailureError("Unexpected JSON shape from contents API")
        return data

    def review_comments(self, *, repo: str, pr: int) -> list[dict[str, Any]]:
        endpoint = f"repos/{repo}/pulls/{pr}/comments"
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

        raise ExecFailureError("Unexpected JSON shape from review comments API")

    def create_review_comment(
        self,
        *,
        repo: str,
        pr: int,
        body: str,
        commit_id: str,
        path: str,
        position: int,
    ) -> dict[str, Any]:
        endpoint = f"repos/{repo}/pulls/{pr}/comments"
        raw = self._run(
            [
                "api",
                "-X",
                "POST",
                endpoint,
                "-f",
                f"body={body}",
                "-f",
                f"commit_id={commit_id}",
                "-f",
                f"path={path}",
                "-F",
                f"position={position}",
            ]
        )
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ExecFailureError("`gh api` returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise ExecFailureError(
                "Unexpected JSON shape from create review comment API"
            )
        return data

    def delete_review_comment(self, *, repo: str, comment_id: int) -> None:
        endpoint = f"repos/{repo}/pulls/comments/{comment_id}"
        self._run(["api", "-X", "DELETE", endpoint])

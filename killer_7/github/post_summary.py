from __future__ import annotations

from collections.abc import Mapping

from .gh import GhClient
from ..report.format_md import format_pr_summary_comment_md


SUMMARY_MARKER = "<!-- killer-7:summary:v1 -->"


def _comment_id(comment: Mapping[str, object]) -> int:
    raw = comment.get("id")
    return raw if isinstance(raw, int) else -1


def post_summary_comment(
    *, repo: str, pr: int, head_sha: str, summary: Mapping[str, object]
) -> dict[str, object]:
    client = GhClient.from_env()
    body = format_pr_summary_comment_md(
        summary,
        marker=SUMMARY_MARKER,
        head_sha=head_sha,
    )

    comments = client.issue_comments(repo=repo, issue=pr)
    existing = [
        c
        for c in comments
        if isinstance(c.get("body"), str) and SUMMARY_MARKER in str(c.get("body"))
    ]

    if existing:
        target = min(existing, key=_comment_id)
        comment_id = _comment_id(target)
        updated = client.update_issue_comment(
            repo=repo, comment_id=comment_id, body=body
        )
        updated_id = _comment_id(updated)
        return {
            "mode": "updated",
            "comment_id": updated_id if updated_id >= 0 else comment_id,
        }

    created = client.create_issue_comment(repo=repo, issue=pr, body=body)
    return {
        "mode": "created",
        "comment_id": _comment_id(created),
    }

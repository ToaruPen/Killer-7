from __future__ import annotations

from collections.abc import Mapping

from ..errors import ExecFailureError
from .gh import GhClient
from ..report.format_md import format_pr_summary_comment_md


SUMMARY_MARKER = "<!-- killer-7:summary:v1 -->"


def _comment_id(comment: Mapping[str, object]) -> int:
    raw = comment.get("id")
    return raw if isinstance(raw, int) else -1


def _marker_comments(
    comments: list[dict[str, object]], *, marker: str
) -> list[dict[str, object]]:
    return [
        c
        for c in comments
        if isinstance(c.get("body"), str) and marker in str(c.get("body"))
    ]


def _latest_marker_comment(
    comments: list[dict[str, object]],
) -> dict[str, object] | None:
    valid = [c for c in comments if _comment_id(c) >= 0]
    if not valid:
        return None
    return max(valid, key=_comment_id)


def _delete_comment_if_exists(*, client: GhClient, repo: str, comment_id: int) -> bool:
    try:
        client.delete_issue_comment(repo=repo, comment_id=comment_id)
        return True
    except ExecFailureError as exc:
        # Concurrent runs may delete the same duplicate; treat as already converged.
        if "not found" in str(exc).lower():
            return False
        raise


def _dedupe_marker_comments(
    *,
    client: GhClient,
    repo: str,
    marker_comments: list[dict[str, object]],
    keep_id: int,
) -> int:
    removed = 0
    for comment in marker_comments:
        comment_id = _comment_id(comment)
        if comment_id < 0 or comment_id == keep_id:
            continue
        if _delete_comment_if_exists(client=client, repo=repo, comment_id=comment_id):
            removed += 1
    return removed


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
    existing = _marker_comments(comments, marker=SUMMARY_MARKER)

    if existing:
        target = _latest_marker_comment(existing)
        if target is None:
            raise ExecFailureError("Marker comments found but none have a valid id")

        keep_id = _comment_id(target)
        updated = client.update_issue_comment(repo=repo, comment_id=keep_id, body=body)
        updated_id = _comment_id(updated)
        if updated_id >= 0:
            keep_id = updated_id

        latest_comments = _marker_comments(
            client.issue_comments(repo=repo, issue=pr), marker=SUMMARY_MARKER
        )
        latest = _latest_marker_comment(latest_comments)
        if latest is not None:
            latest_id = _comment_id(latest)
            if latest_id >= 0 and latest_id != keep_id:
                _ = client.update_issue_comment(
                    repo=repo, comment_id=latest_id, body=body
                )
                keep_id = latest_id

        removed = _dedupe_marker_comments(
            client=client,
            repo=repo,
            marker_comments=_marker_comments(
                client.issue_comments(repo=repo, issue=pr), marker=SUMMARY_MARKER
            ),
            keep_id=keep_id,
        )
        return {
            "mode": "updated",
            "comment_id": keep_id,
            "deduped": removed,
        }

    created = client.create_issue_comment(repo=repo, issue=pr, body=body)
    created_id = _comment_id(created)

    latest_comments = _marker_comments(
        client.issue_comments(repo=repo, issue=pr), marker=SUMMARY_MARKER
    )
    latest = _latest_marker_comment(latest_comments)

    keep_id = created_id
    mode = "created"
    if latest is not None:
        latest_id = _comment_id(latest)
        if latest_id >= 0:
            keep_id = latest_id
            if latest_id != created_id:
                mode = "reconciled"
            _ = client.update_issue_comment(repo=repo, comment_id=keep_id, body=body)

    removed = _dedupe_marker_comments(
        client=client,
        repo=repo,
        marker_comments=_marker_comments(
            client.issue_comments(repo=repo, issue=pr), marker=SUMMARY_MARKER
        ),
        keep_id=keep_id,
    )

    return {
        "mode": mode,
        "comment_id": keep_id,
        "deduped": removed,
    }

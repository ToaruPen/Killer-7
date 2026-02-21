from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from ..errors import ExecFailureError
from ..report.format_md import format_pr_summary_comment_md
from .gh import GhClient

SUMMARY_MARKER = "<!-- killer-7:summary:v1 -->"


def _comment_id(comment: Mapping[str, object]) -> int:
    raw = comment.get("id")
    return raw if isinstance(raw, int) else -1


def _is_not_found_error(exc: ExecFailureError) -> bool:
    return "not found" in str(exc).lower()


def _ensure_pr_head_unchanged(
    *, client: GhClient, repo: str, pr: int, expected_head_sha: str
) -> None:
    current_head_sha = client.pr_head_ref_oid(repo=repo, pr=pr)
    if current_head_sha != expected_head_sha:
        raise ExecFailureError("PR head changed; skip stale summary mutation")


def _comment_author_login(comment: Mapping[str, object]) -> str:
    user_obj = comment.get("user")
    if not isinstance(user_obj, dict):
        return ""
    user_dict = cast(dict[str, object], user_obj)
    login_obj = user_dict.get("login")
    return login_obj.strip() if isinstance(login_obj, str) else ""


def _marker_comments(
    comments: list[dict[str, object]], *, marker: str, author_login: str
) -> list[dict[str, object]]:
    return [
        c
        for c in comments
        if _comment_author_login(c) == author_login
        and isinstance(c.get("body"), str)
        and marker in str(c.get("body"))
    ]


def _latest_marker_comment(
    comments: list[dict[str, object]],
) -> dict[str, object] | None:
    valid = [c for c in comments if _comment_id(c) >= 0]
    if not valid:
        return None
    return max(valid, key=_comment_id)


def _marker_comment_ids(comments: list[dict[str, object]]) -> set[int]:
    return {_comment_id(c) for c in comments if _comment_id(c) >= 0}


def _delete_comment_if_exists(
    *,
    client: GhClient,
    repo: str,
    pr: int,
    expected_head_sha: str,
    comment_id: int,
) -> bool:
    try:
        _ensure_pr_head_unchanged(
            client=client,
            repo=repo,
            pr=pr,
            expected_head_sha=expected_head_sha,
        )
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
    pr: int,
    expected_head_sha: str,
    marker_comments: list[dict[str, object]],
    keep_id: int,
) -> int:
    if keep_id not in _marker_comment_ids(marker_comments):
        return 0

    removed = 0
    for comment in marker_comments:
        comment_id = _comment_id(comment)
        if comment_id < 0 or comment_id == keep_id:
            continue
        if _delete_comment_if_exists(
            client=client,
            repo=repo,
            pr=pr,
            expected_head_sha=expected_head_sha,
            comment_id=comment_id,
        ):
            removed += 1
    return removed


def _create_marker_comment(
    *,
    client: GhClient,
    repo: str,
    pr: int,
    expected_head_sha: str,
    body: str,
) -> int:
    _ensure_pr_head_unchanged(
        client=client,
        repo=repo,
        pr=pr,
        expected_head_sha=expected_head_sha,
    )
    created = client.create_issue_comment(repo=repo, issue=pr, body=body)
    created_id = _comment_id(created)
    if created_id < 0:
        raise ExecFailureError("Created marker comment missing valid id")
    return created_id


def _latest_marker_id(
    *, client: GhClient, repo: str, pr: int, author_login: str
) -> int | None:
    latest = _latest_marker_comment(
        _marker_comments(
            client.issue_comments(repo=repo, issue=pr),
            marker=SUMMARY_MARKER,
            author_login=author_login,
        )
    )
    if latest is None:
        return None
    latest_id = _comment_id(latest)
    return latest_id if latest_id >= 0 else None


def _update_with_not_found_recovery(
    *,
    client: GhClient,
    repo: str,
    pr: int,
    author_login: str,
    expected_head_sha: str,
    preferred_comment_id: int,
    body: str,
) -> int:
    candidate_id = preferred_comment_id
    for _ in range(3):
        try:
            _ensure_pr_head_unchanged(
                client=client,
                repo=repo,
                pr=pr,
                expected_head_sha=expected_head_sha,
            )
            updated = client.update_issue_comment(
                repo=repo, comment_id=candidate_id, body=body
            )
            updated_id = _comment_id(updated)
            return updated_id if updated_id >= 0 else candidate_id
        except ExecFailureError as exc:
            if not _is_not_found_error(exc):
                raise
            latest_id = _latest_marker_id(
                client=client, repo=repo, pr=pr, author_login=author_login
            )
            if latest_id is None:
                return _create_marker_comment(
                    client=client,
                    repo=repo,
                    pr=pr,
                    expected_head_sha=expected_head_sha,
                    body=body,
                )
            candidate_id = latest_id

    raise ExecFailureError("Failed to update marker comment after race recovery")


def _ensure_keep_marker_exists(
    *,
    client: GhClient,
    repo: str,
    pr: int,
    author_login: str,
    expected_head_sha: str,
    keep_id: int,
    body: str,
) -> int:
    current_markers = _marker_comments(
        client.issue_comments(repo=repo, issue=pr),
        marker=SUMMARY_MARKER,
        author_login=author_login,
    )
    if any(_comment_id(c) == keep_id for c in current_markers):
        return keep_id

    latest = _latest_marker_comment(current_markers)
    if latest is not None:
        latest_id = _comment_id(latest)
        if latest_id >= 0:
            return _update_with_not_found_recovery(
                client=client,
                repo=repo,
                pr=pr,
                author_login=author_login,
                expected_head_sha=expected_head_sha,
                preferred_comment_id=latest_id,
                body=body,
            )

    return _create_marker_comment(
        client=client,
        repo=repo,
        pr=pr,
        expected_head_sha=expected_head_sha,
        body=body,
    )


def _dedupe_with_keep_recovery(
    *,
    client: GhClient,
    repo: str,
    pr: int,
    author_login: str,
    expected_head_sha: str,
    keep_id: int,
    body: str,
) -> tuple[int, int]:
    marker_comments = _marker_comments(
        client.issue_comments(repo=repo, issue=pr),
        marker=SUMMARY_MARKER,
        author_login=author_login,
    )
    if keep_id not in _marker_comment_ids(marker_comments):
        keep_id = _ensure_keep_marker_exists(
            client=client,
            repo=repo,
            pr=pr,
            author_login=author_login,
            expected_head_sha=expected_head_sha,
            keep_id=keep_id,
            body=body,
        )
        marker_comments = _marker_comments(
            client.issue_comments(repo=repo, issue=pr),
            marker=SUMMARY_MARKER,
            author_login=author_login,
        )

    removed = _dedupe_marker_comments(
        client=client,
        repo=repo,
        pr=pr,
        expected_head_sha=expected_head_sha,
        marker_comments=marker_comments,
        keep_id=keep_id,
    )

    final_comments = _marker_comments(
        client.issue_comments(repo=repo, issue=pr),
        marker=SUMMARY_MARKER,
        author_login=author_login,
    )
    final_ids = _marker_comment_ids(final_comments)
    if keep_id not in final_ids:
        keep_id = _ensure_keep_marker_exists(
            client=client,
            repo=repo,
            pr=pr,
            author_login=author_login,
            expected_head_sha=expected_head_sha,
            keep_id=keep_id,
            body=body,
        )

        final_comments = _marker_comments(
            client.issue_comments(repo=repo, issue=pr),
            marker=SUMMARY_MARKER,
            author_login=author_login,
        )
        final_ids = _marker_comment_ids(final_comments)

    if len(final_ids) > 1:
        removed += _dedupe_marker_comments(
            client=client,
            repo=repo,
            pr=pr,
            expected_head_sha=expected_head_sha,
            marker_comments=final_comments,
            keep_id=keep_id,
        )
        keep_id = _ensure_keep_marker_exists(
            client=client,
            repo=repo,
            pr=pr,
            author_login=author_login,
            expected_head_sha=expected_head_sha,
            keep_id=keep_id,
            body=body,
        )

        post_recovery_comments = _marker_comments(
            client.issue_comments(repo=repo, issue=pr),
            marker=SUMMARY_MARKER,
            author_login=author_login,
        )
        if len(_marker_comment_ids(post_recovery_comments)) > 1:
            removed += _dedupe_marker_comments(
                client=client,
                repo=repo,
                pr=pr,
                expected_head_sha=expected_head_sha,
                marker_comments=post_recovery_comments,
                keep_id=keep_id,
            )
            keep_id = _ensure_keep_marker_exists(
                client=client,
                repo=repo,
                pr=pr,
                author_login=author_login,
                expected_head_sha=expected_head_sha,
                keep_id=keep_id,
                body=body,
            )

    return keep_id, removed


def post_summary_comment(
    *,
    repo: str,
    pr: int,
    head_sha: str,
    expected_head_sha: str,
    summary: Mapping[str, object],
) -> dict[str, object]:
    client = GhClient.from_env()
    _ensure_pr_head_unchanged(
        client=client,
        repo=repo,
        pr=pr,
        expected_head_sha=expected_head_sha,
    )
    author_login = client.viewer_login()
    body = format_pr_summary_comment_md(
        summary,
        marker=SUMMARY_MARKER,
        head_sha=head_sha,
    )

    comments = client.issue_comments(repo=repo, issue=pr)
    existing = _marker_comments(
        comments,
        marker=SUMMARY_MARKER,
        author_login=author_login,
    )

    if existing:
        target = _latest_marker_comment(existing)
        if target is None:
            raise ExecFailureError("Marker comments found but none have a valid id")

        keep_id = _comment_id(target)
        keep_id = _update_with_not_found_recovery(
            client=client,
            repo=repo,
            pr=pr,
            author_login=author_login,
            expected_head_sha=expected_head_sha,
            preferred_comment_id=keep_id,
            body=body,
        )

        latest_comments = _marker_comments(
            client.issue_comments(repo=repo, issue=pr),
            marker=SUMMARY_MARKER,
            author_login=author_login,
        )
        latest = _latest_marker_comment(latest_comments)
        if latest is not None:
            latest_id = _comment_id(latest)
            if latest_id >= 0 and latest_id != keep_id:
                keep_id = _update_with_not_found_recovery(
                    client=client,
                    repo=repo,
                    pr=pr,
                    author_login=author_login,
                    expected_head_sha=expected_head_sha,
                    preferred_comment_id=latest_id,
                    body=body,
                )

        keep_id = _ensure_keep_marker_exists(
            client=client,
            repo=repo,
            pr=pr,
            author_login=author_login,
            expected_head_sha=expected_head_sha,
            keep_id=keep_id,
            body=body,
        )

        keep_id, removed = _dedupe_with_keep_recovery(
            client=client,
            repo=repo,
            pr=pr,
            author_login=author_login,
            expected_head_sha=expected_head_sha,
            keep_id=keep_id,
            body=body,
        )
        return {
            "mode": "updated",
            "comment_id": keep_id,
            "deduped": removed,
        }

    created_id = _create_marker_comment(
        client=client,
        repo=repo,
        pr=pr,
        expected_head_sha=expected_head_sha,
        body=body,
    )

    latest_comments = _marker_comments(
        client.issue_comments(repo=repo, issue=pr),
        marker=SUMMARY_MARKER,
        author_login=author_login,
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
            keep_id = _update_with_not_found_recovery(
                client=client,
                repo=repo,
                pr=pr,
                author_login=author_login,
                expected_head_sha=expected_head_sha,
                preferred_comment_id=keep_id,
                body=body,
            )

    keep_id = _ensure_keep_marker_exists(
        client=client,
        repo=repo,
        pr=pr,
        author_login=author_login,
        expected_head_sha=expected_head_sha,
        keep_id=keep_id,
        body=body,
    )

    keep_id, removed = _dedupe_with_keep_recovery(
        client=client,
        repo=repo,
        pr=pr,
        author_login=author_login,
        expected_head_sha=expected_head_sha,
        keep_id=keep_id,
        body=body,
    )

    return {
        "mode": mode,
        "comment_id": keep_id,
        "deduped": removed,
    }

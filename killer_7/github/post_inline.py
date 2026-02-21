from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, cast

from ..errors import BlockedError, ExecFailureError
from ..report.fingerprint import finding_fingerprint
from .diff_map import build_right_line_to_position_map
from .gh import GhClient
from .inline_select import InlineCandidate, select_inline_candidates

INLINE_MARKER_PREFIX = "<!-- killer-7:inline:v1 fp="
INLINE_MARKER_SUFFIX = " -->"
INLINE_LIMIT = 150


class _InlineClient(Protocol):
    def pr_head_ref_oid(self, *, repo: str, pr: int) -> str: ...

    def viewer_login(self) -> str: ...

    def review_comments(self, *, repo: str, pr: int) -> list[dict[str, object]]: ...

    def create_review_comment(
        self,
        *,
        repo: str,
        pr: int,
        body: str,
        commit_id: str,
        path: str,
        position: int,
    ) -> dict[str, object]: ...

    def delete_review_comment(self, *, repo: str, comment_id: int) -> None: ...


def _comment_id(comment: Mapping[str, object]) -> int:
    raw = comment.get("id")
    return raw if isinstance(raw, int) else -1


def _comment_path(comment: Mapping[str, object]) -> str:
    raw = comment.get("path")
    return raw.strip() if isinstance(raw, str) else ""


def _comment_position(comment: Mapping[str, object]) -> int:
    raw = comment.get("position")
    return raw if isinstance(raw, int) else -1


def _comment_author_login(comment: Mapping[str, object]) -> str:
    user_obj = comment.get("user")
    if not isinstance(user_obj, dict):
        return ""
    user = cast(dict[str, object], user_obj)
    raw = user.get("login")
    return raw.strip() if isinstance(raw, str) else ""


def _extract_fingerprint(body: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if not s.startswith(INLINE_MARKER_PREFIX):
            continue
        if not s.endswith(INLINE_MARKER_SUFFIX):
            continue
        return s[len(INLINE_MARKER_PREFIX) : -len(INLINE_MARKER_SUFFIX)].strip()
    return ""


def _is_not_found_error(exc: ExecFailureError) -> bool:
    return "not found" in str(exc).lower()


def _ensure_pr_head_unchanged(
    *, client: _InlineClient, repo: str, pr: int, expected_head_sha: str
) -> None:
    current_head_sha = client.pr_head_ref_oid(repo=repo, pr=pr)
    if current_head_sha != expected_head_sha:
        raise ExecFailureError("PR head changed; skip stale inline mutation")


def _format_inline_body(finding: Mapping[str, object], *, fingerprint: str) -> str:
    title = finding.get("title")
    body = finding.get("body")
    priority = finding.get("priority")

    title_txt = title.strip() if isinstance(title, str) else ""
    body_txt = body.strip() if isinstance(body, str) else ""
    pr_txt = priority.strip() if isinstance(priority, str) else ""

    lines: list[str] = [
        f"{INLINE_MARKER_PREFIX}{fingerprint}{INLINE_MARKER_SUFFIX}",
        f"[{pr_txt}] {title_txt}".strip(),
    ]
    if body_txt:
        lines.append("")
        lines.append(body_txt)
    return "\n".join(lines).rstrip("\n") + "\n"


def _inline_finding(
    review_summary: Mapping[str, object], *, candidate: InlineCandidate
) -> Mapping[str, object]:
    findings_obj = review_summary.get("findings")
    if not isinstance(findings_obj, list):
        return {}

    findings = cast(list[object], findings_obj)
    for raw in findings:
        if not isinstance(raw, Mapping):
            continue
        item = cast(Mapping[str, object], raw)
        if finding_fingerprint(item) == candidate.fingerprint:
            return item
    return {}


def _delete_existing_inline_comments(
    *,
    client: _InlineClient,
    repo: str,
    pr: int,
    expected_head_sha: str,
) -> int:
    _ensure_pr_head_unchanged(
        client=client,
        repo=repo,
        pr=pr,
        expected_head_sha=expected_head_sha,
    )

    viewer_login = client.viewer_login()
    existing = client.review_comments(repo=repo, pr=pr)

    deleted = 0
    for raw in existing:
        if not isinstance(raw, dict):
            continue
        if _comment_author_login(raw) != viewer_login:
            continue
        body_obj = raw.get("body")
        body = body_obj if isinstance(body_obj, str) else ""
        if not _extract_fingerprint(body):
            continue

        comment_id = _comment_id(raw)
        if comment_id < 0:
            continue

        _ensure_pr_head_unchanged(
            client=client,
            repo=repo,
            pr=pr,
            expected_head_sha=expected_head_sha,
        )
        try:
            client.delete_review_comment(repo=repo, comment_id=comment_id)
        except ExecFailureError as exc:
            if not _is_not_found_error(exc):
                raise
            continue

        _ensure_pr_head_unchanged(
            client=client,
            repo=repo,
            pr=pr,
            expected_head_sha=expected_head_sha,
        )
        deleted += 1
    return deleted


def post_inline_comments(
    *,
    repo: str,
    pr: int,
    head_sha: str,
    expected_head_sha: str,
    review_summary: Mapping[str, object],
    diff_patch: str,
    client: _InlineClient | None = None,
) -> dict[str, object]:
    gh: _InlineClient = client if client is not None else GhClient.from_env()

    line_map = build_right_line_to_position_map(diff_patch)
    selected = select_inline_candidates(review_summary, line_map=line_map)
    eligible = [
        c for c in selected if c.inline_eligible and c.diff_position is not None
    ]

    ineligible = [
        c for c in selected if (not c.inline_eligible) or (c.diff_position is None)
    ]
    if len(eligible) > INLINE_LIMIT:
        deleted = _delete_existing_inline_comments(
            client=gh,
            repo=repo,
            pr=pr,
            expected_head_sha=expected_head_sha,
        )
        return {
            "mode": "blocked_over_limit",
            "blocked": True,
            "eligible_count": len(eligible),
            "created": 0,
            "deleted": deleted,
        }

    if ineligible:
        deleted = _delete_existing_inline_comments(
            client=gh,
            repo=repo,
            pr=pr,
            expected_head_sha=expected_head_sha,
        )
        unmatched = [
            {
                "fingerprint": c.fingerprint,
                "path": c.repo_relative_path,
                "line": c.start_line,
                "priority": c.priority,
                "reason": c.skip_reason,
            }
            for c in ineligible
        ]
        return {
            "mode": "blocked_unmappable_locations",
            "blocked": True,
            "eligible_count": len(eligible),
            "unmappable_count": len(ineligible),
            "created": 0,
            "deleted": deleted,
            "unmapped_findings": unmatched,
        }

    desired: dict[str, InlineCandidate] = {}
    for c in eligible:
        desired[c.fingerprint] = c

    viewer_login = gh.viewer_login()
    existing = gh.review_comments(repo=repo, pr=pr)

    existing_by_fp: dict[str, list[dict[str, object]]] = {}
    for raw in existing:
        if _comment_author_login(raw) != viewer_login:
            continue
        body_obj = raw.get("body")
        body = body_obj if isinstance(body_obj, str) else ""
        fp = _extract_fingerprint(body)
        if not fp:
            continue
        existing_by_fp.setdefault(fp, []).append(raw)

    deleted = 0
    created = 0

    for fp, comments in existing_by_fp.items():
        if fp in desired:
            continue
        for comment in comments:
            comment_id = _comment_id(comment)
            if comment_id < 0:
                continue
            _ensure_pr_head_unchanged(
                client=gh,
                repo=repo,
                pr=pr,
                expected_head_sha=expected_head_sha,
            )
            try:
                gh.delete_review_comment(repo=repo, comment_id=comment_id)
            except ExecFailureError as exc:
                if not _is_not_found_error(exc):
                    raise
            deleted += 1

    for fp, candidate in desired.items():
        finding = _inline_finding(review_summary, candidate=candidate)
        if not finding:
            continue

        body = _format_inline_body(finding, fingerprint=fp)
        candidate_path = candidate.repo_relative_path
        candidate_pos = candidate.diff_position
        if candidate_pos is None or candidate_pos <= 0:
            continue

        comments = existing_by_fp.get(fp, [])
        keep: dict[str, object] | None = None
        for comment in comments:
            if (
                _comment_path(comment) == candidate_path
                and _comment_position(comment) == candidate_pos
            ):
                if keep is None or _comment_id(comment) > _comment_id(keep):
                    keep = comment

        if keep is not None:
            keep_id = _comment_id(keep)
            for comment in comments:
                comment_id = _comment_id(comment)
                if comment_id < 0 or comment_id == keep_id:
                    continue
                _ensure_pr_head_unchanged(
                    client=gh,
                    repo=repo,
                    pr=pr,
                    expected_head_sha=expected_head_sha,
                )
                try:
                    gh.delete_review_comment(repo=repo, comment_id=comment_id)
                except ExecFailureError as exc:
                    if not _is_not_found_error(exc):
                        raise
                deleted += 1
            continue

        for comment in comments:
            comment_id = _comment_id(comment)
            if comment_id < 0:
                continue
            _ensure_pr_head_unchanged(
                client=gh,
                repo=repo,
                pr=pr,
                expected_head_sha=expected_head_sha,
            )
            try:
                gh.delete_review_comment(repo=repo, comment_id=comment_id)
            except ExecFailureError as exc:
                if not _is_not_found_error(exc):
                    raise
            deleted += 1

        _ensure_pr_head_unchanged(
            client=gh,
            repo=repo,
            pr=pr,
            expected_head_sha=expected_head_sha,
        )
        gh.create_review_comment(
            repo=repo,
            pr=pr,
            body=body,
            commit_id=head_sha,
            path=candidate_path,
            position=candidate_pos,
        )
        created += 1

    _ensure_pr_head_unchanged(
        client=gh,
        repo=repo,
        pr=pr,
        expected_head_sha=expected_head_sha,
    )

    return {
        "mode": "ok",
        "blocked": False,
        "eligible_count": len(eligible),
        "created": created,
        "deleted": deleted,
    }


def raise_if_inline_blocked(result: Mapping[str, object]) -> None:
    blocked = result.get("blocked") is True
    if not blocked:
        return

    mode = result.get("mode")
    if mode == "blocked_over_limit":
        count_obj = result.get("eligible_count")
        count = count_obj if isinstance(count_obj, int) else 0
        raise BlockedError(
            f"Inline posting blocked: P0/P1 eligible findings exceed {INLINE_LIMIT} (count={count})"
        )

    if mode == "blocked_unmappable_locations":
        count_obj = result.get("unmappable_count")
        count = count_obj if isinstance(count_obj, int) else 0
        if count == 0:
            bad_obj = result.get("unmapped_findings")
            if isinstance(bad_obj, list):
                count = len(bad_obj)

        bad = result.get("unmapped_findings")
        examples = []
        if isinstance(bad, list):
            for item in bad[:3]:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                line = item.get("line")
                reason = item.get("reason")
                if (
                    isinstance(path, str)
                    and path.strip()
                    and isinstance(line, int)
                    and line > 0
                ):
                    examples.append(f"{path}:{line}({reason})")
        examples_txt = ", ".join(examples)
        detail = f" Examples: {examples_txt}" if examples_txt else ""
        raise BlockedError(
            f"Inline posting blocked: P0/P1 findings include {count} unmappable code locations."
            + detail
        )

    raise BlockedError(f"Inline posting blocked (mode={mode!r})")

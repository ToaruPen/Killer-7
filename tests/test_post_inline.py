from __future__ import annotations

import unittest
from typing import cast


class _FakeGhClient:
    def __init__(self) -> None:
        self._comments: list[dict[str, object]] = []
        self._next_id: int = 1
        self.created: int = 0
        self.deleted: int = 0
        self.head_checks: int = 0

    def pr_head_ref_oid(self, *, repo: str, pr: int) -> str:
        self.head_checks += 1
        return "0123456789abcdef"

    def viewer_login(self) -> str:
        return "owner"

    def review_comments(self, *, repo: str, pr: int) -> list[dict[str, object]]:
        return [dict(c) for c in self._comments]

    def create_review_comment(
        self,
        *,
        repo: str,
        pr: int,
        body: str,
        commit_id: str,
        path: str,
        position: int,
    ) -> dict[str, object]:
        comment = {
            "id": self._next_id,
            "body": body,
            "path": path,
            "position": position,
            "user": {"login": "owner"},
        }
        self._next_id += 1
        self._comments.append(cast(dict[str, object], comment))
        self.created += 1
        return cast(dict[str, object], dict(comment))

    def delete_review_comment(self, *, repo: str, comment_id: int) -> None:
        kept: list[dict[str, object]] = []
        for comment in self._comments:
            raw_id = comment.get("id")
            cid = raw_id if isinstance(raw_id, int) else -1
            if cid != comment_id:
                kept.append(comment)
        self._comments = kept
        self.deleted += 1


class _FakeGhClientWithHeadSequence(_FakeGhClient):
    def __init__(self, sequence: list[str]) -> None:
        super().__init__()
        self._sequence = sequence

    def pr_head_ref_oid(self, *, repo: str, pr: int) -> str:
        self.head_checks += 1
        if self._sequence:
            return self._sequence.pop(0)
        return "fedcba9876543210"


def _summary_with_findings(findings: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 3,
        "scope_id": "owner/name#pr-123@0123456789ab",
        "status": "Approved",
        "findings": findings,
        "questions": [],
        "overall_explanation": "ok",
    }


def _finding(*, title: str, priority: str, line: int) -> dict[str, object]:
    return {
        "title": title,
        "body": f"{title} body",
        "priority": priority,
        "sources": [f"src/app.py#L{line}-L{line}"],
        "code_location": {
            "repo_relative_path": "src/app.py",
            "line_range": {"start": line, "end": line},
        },
    }


def _patch_new_file_three_lines() -> str:
    return "\n".join(
        [
            "diff --git a/src/app.py b/src/app.py",
            "new file mode 100644",
            "index 0000000..1111111",
            "--- /dev/null",
            "+++ b/src/app.py",
            "@@ -0,0 +1,3 @@",
            "+line-1",
            "+line-2",
            "+line-3",
            "",
        ]
    )


def _patch_shifted_position_for_line2() -> str:
    return "\n".join(
        [
            "diff --git a/src/app.py b/src/app.py",
            "index 1111111..2222222 100644",
            "--- a/src/app.py",
            "+++ b/src/app.py",
            "@@ -1,2 +1,2 @@",
            "-old-line-1",
            "+new-line-1",
            " line-2",
            "",
        ]
    )


class TestPostInline(unittest.TestCase):
    def test_posts_only_p0_p1_inline(self) -> None:
        from killer_7.github.post_inline import post_inline_comments

        client = _FakeGhClient()
        summary = _summary_with_findings(
            [
                _finding(title="must-fix", priority="P0", line=1),
                _finding(title="high", priority="P1", line=2),
                _finding(title="nit", priority="P2", line=3),
            ]
        )

        result = post_inline_comments(
            repo="owner/name",
            pr=123,
            head_sha="0123456789abcdef",
            expected_head_sha="0123456789abcdef",
            review_summary=summary,
            diff_patch=_patch_new_file_three_lines(),
            client=client,
        )

        self.assertEqual(result["blocked"], False)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(client.review_comments(repo="owner/name", pr=123)), 2)

    def test_idempotent_and_recreates_when_position_changes(self) -> None:
        from killer_7.github.post_inline import post_inline_comments

        client = _FakeGhClient()
        summary = _summary_with_findings(
            [_finding(title="same-finding", priority="P0", line=2)]
        )

        first = post_inline_comments(
            repo="owner/name",
            pr=123,
            head_sha="0123456789abcdef",
            expected_head_sha="0123456789abcdef",
            review_summary=summary,
            diff_patch=_patch_new_file_three_lines(),
            client=client,
        )
        self.assertEqual(first["created"], 1)
        self.assertEqual(first["deleted"], 0)

        second = post_inline_comments(
            repo="owner/name",
            pr=123,
            head_sha="0123456789abcdef",
            expected_head_sha="0123456789abcdef",
            review_summary=summary,
            diff_patch=_patch_new_file_three_lines(),
            client=client,
        )
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["deleted"], 0)

        moved = post_inline_comments(
            repo="owner/name",
            pr=123,
            head_sha="0123456789abcdef",
            expected_head_sha="0123456789abcdef",
            review_summary=summary,
            diff_patch=_patch_shifted_position_for_line2(),
            client=client,
        )
        self.assertEqual(moved["created"], 1)
        self.assertEqual(moved["deleted"], 1)
        self.assertEqual(len(client.review_comments(repo="owner/name", pr=123)), 1)

    def test_blocks_when_inline_targets_exceed_150(self) -> None:
        from killer_7.github.post_inline import post_inline_comments

        client = _FakeGhClient()
        findings = [
            _finding(title=f"f-{i}", priority="P1", line=i) for i in range(1, 152)
        ]
        summary = _summary_with_findings(findings)

        patch_lines = [
            "diff --git a/src/app.py b/src/app.py",
            "new file mode 100644",
            "index 0000000..1111111",
            "--- /dev/null",
            "+++ b/src/app.py",
            "@@ -0,0 +1,200 @@",
        ]
        patch_lines.extend([f"+line-{i}" for i in range(1, 201)])
        patch_lines.append("")

        result = post_inline_comments(
            repo="owner/name",
            pr=123,
            head_sha="0123456789abcdef",
            expected_head_sha="0123456789abcdef",
            review_summary=summary,
            diff_patch="\n".join(patch_lines),
            client=client,
        )

        self.assertEqual(result["blocked"], True)
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["eligible_count"], 151)
        self.assertEqual(len(client.review_comments(repo="owner/name", pr=123)), 0)

    def test_over_limit_deletes_existing_inline_comments(self) -> None:
        from killer_7.github.post_inline import post_inline_comments

        client = _FakeGhClient()

        first = post_inline_comments(
            repo="owner/name",
            pr=123,
            head_sha="0123456789abcdef",
            expected_head_sha="0123456789abcdef",
            review_summary=_summary_with_findings(
                [_finding(title="mapped", priority="P0", line=1)]
            ),
            diff_patch=_patch_new_file_three_lines(),
            client=client,
        )
        self.assertEqual(first["blocked"], False)
        self.assertEqual(len(client.review_comments(repo="owner/name", pr=123)), 1)

        findings = [
            _finding(title=f"f-{i}", priority="P1", line=i) for i in range(1, 152)
        ]
        summary = _summary_with_findings(findings)

        patch_lines = [
            "diff --git a/src/app.py b/src/app.py",
            "new file mode 100644",
            "index 0000000..1111111",
            "--- /dev/null",
            "+++ b/src/app.py",
            "@@ -0,0 +1,200 @@",
        ]
        patch_lines.extend([f"+line-{i}" for i in range(1, 201)])
        patch_lines.append("")

        result = post_inline_comments(
            repo="owner/name",
            pr=123,
            head_sha="0123456789abcdef",
            expected_head_sha="0123456789abcdef",
            review_summary=summary,
            diff_patch="\n".join(patch_lines),
            client=client,
        )

        self.assertEqual(result["mode"], "blocked_over_limit")
        self.assertEqual(result["blocked"], True)
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(len(client.review_comments(repo="owner/name", pr=123)), 0)

    def test_unmappable_deletes_existing_inline_comments(self) -> None:
        from killer_7.github.post_inline import post_inline_comments

        client = _FakeGhClient()

        first = post_inline_comments(
            repo="owner/name",
            pr=123,
            head_sha="0123456789abcdef",
            expected_head_sha="0123456789abcdef",
            review_summary=_summary_with_findings(
                [_finding(title="mapped", priority="P0", line=1)]
            ),
            diff_patch=_patch_new_file_three_lines(),
            client=client,
        )
        self.assertEqual(first["blocked"], False)
        self.assertEqual(len(client.review_comments(repo="owner/name", pr=123)), 1)

        summary = _summary_with_findings(
            [
                _finding(title="mapped", priority="P0", line=1),
                {
                    "title": "unmapped",
                    "body": "unmapped body",
                    "priority": "P1",
                    "sources": ["src/app.py#L77-L77"],
                    "code_location": {
                        "repo_relative_path": "src/app.py",
                        "line_range": {"start": 77, "end": 77},
                    },
                },
            ]
        )

        result = post_inline_comments(
            repo="owner/name",
            pr=123,
            head_sha="0123456789abcdef",
            expected_head_sha="0123456789abcdef",
            review_summary=summary,
            diff_patch=_patch_new_file_three_lines(),
            client=client,
        )

        self.assertEqual(result["mode"], "blocked_unmappable_locations")
        self.assertEqual(result["blocked"], True)
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(len(client.review_comments(repo="owner/name", pr=123)), 0)

    def test_rejects_when_inline_mapping_fails_for_any_finding(self) -> None:
        from killer_7.github.post_inline import post_inline_comments

        client = _FakeGhClient()
        summary = _summary_with_findings(
            [
                _finding(title="mapped", priority="P0", line=1),
                {
                    "title": "unmapped",
                    "body": "unmapped body",
                    "priority": "P1",
                    "sources": ["src/app.py#L77-L77"],
                    "code_location": {
                        "repo_relative_path": "src/app.py",
                        "line_range": {"start": 77, "end": 77},
                    },
                },
            ]
        )

        result = post_inline_comments(
            repo="owner/name",
            pr=123,
            head_sha="0123456789abcdef",
            expected_head_sha="0123456789abcdef",
            review_summary=summary,
            diff_patch=_patch_new_file_three_lines(),
            client=client,
        )

        self.assertEqual(result["mode"], "blocked_unmappable_locations")
        self.assertEqual(result["blocked"], True)
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(client.review_comments(repo="owner/name", pr=123)), 0)
        self.assertIn("unmapped_findings", result)

    def test_rejects_invalid_code_location(self) -> None:
        from killer_7.github.post_inline import post_inline_comments

        client = _FakeGhClient()
        summary = _summary_with_findings(
            [
                {
                    "title": "invalid",
                    "body": "invalid body",
                    "priority": "P0",
                    "sources": ["#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "",
                        "line_range": {"start": 1, "end": 1},
                    },
                }
            ]
        )

        result = post_inline_comments(
            repo="owner/name",
            pr=123,
            head_sha="0123456789abcdef",
            expected_head_sha="0123456789abcdef",
            review_summary=summary,
            diff_patch=_patch_new_file_three_lines(),
            client=client,
        )

        self.assertEqual(result["mode"], "blocked_unmappable_locations")
        self.assertEqual(result["blocked"], True)
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["deleted"], 0)

    def test_fails_when_head_moves_after_inline_mutation(self) -> None:
        from killer_7.errors import ExecFailureError
        from killer_7.github.post_inline import post_inline_comments

        client = _FakeGhClientWithHeadSequence(["0123456789abcdef", "fedcba9876543210"])
        summary = _summary_with_findings(
            [_finding(title="must-fix", priority="P0", line=1)]
        )

        with self.assertRaises(ExecFailureError):
            post_inline_comments(
                repo="owner/name",
                pr=123,
                head_sha="0123456789abcdef",
                expected_head_sha="0123456789abcdef",
                review_summary=summary,
                diff_patch=_patch_new_file_three_lines(),
                client=client,
            )


if __name__ == "__main__":
    raise SystemExit(unittest.main())

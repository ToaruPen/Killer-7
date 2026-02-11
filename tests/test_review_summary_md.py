from __future__ import annotations

import unittest

from killer_7.report.format_md import (
    format_pr_summary_comment_md,
    format_review_summary_md,
)


class TestReviewSummaryMd(unittest.TestCase):
    def test_p2_p3_are_collapsed(self) -> None:
        summary = {
            "schema_version": 3,
            "scope_id": "owner/name#pr-1@deadbeef",
            "status": "Approved with nits",
            "findings": [
                {
                    "title": "P0 title",
                    "body": "body",
                    "priority": "P0",
                    "sources": ["hello.txt#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "hello.txt",
                        "line_range": {"start": 1, "end": 1},
                    },
                },
                {
                    "title": "P2 title",
                    "body": "body",
                    "priority": "P2",
                    "sources": ["hello.txt#L1-L1"],
                    "code_location": {
                        "repo_relative_path": "hello.txt",
                        "line_range": {"start": 1, "end": 1},
                    },
                },
            ],
            "questions": [],
            "overall_explanation": "ok",
            "aspect_statuses": {},
        }

        md = format_review_summary_md(summary)

        self.assertIn("[P0] P0 title", md)
        self.assertIn("[P2] P2 title", md)

        # P2/P3 must be collapsed under <details>.
        self.assertIn("<details>", md)
        self.assertLess(md.index("[P0] P0 title"), md.index("<details>"))
        self.assertGreater(md.index("[P2] P2 title"), md.index("<details>"))

    def test_pr_summary_comment_includes_marker_counts_and_meta(self) -> None:
        summary = {
            "schema_version": 3,
            "scope_id": "owner/name#pr-1@deadbeef",
            "status": "Blocked",
            "findings": [
                {"title": "p0", "priority": "P0", "verified": True},
                {"title": "p1", "priority": "P1", "verified": False},
                {"title": "p2", "priority": "P2", "verified": True},
                {"title": "p3", "priority": "P3", "verified": False},
            ],
            "questions": ["question"],
            "overall_explanation": "blocked reason",
            "aspect_statuses": {},
        }

        md = format_pr_summary_comment_md(
            summary,
            marker="<!-- killer-7:summary:v1 -->",
            head_sha="0123456789abcdef",
        )

        self.assertIn("<!-- killer-7:summary:v1 -->", md)
        self.assertIn("- P0: 1", md)
        self.assertIn("- P1: 1", md)
        self.assertIn("- P2: 1", md)
        self.assertIn("- P3: 1", md)
        self.assertIn("- verified: 2", md)
        self.assertIn("- unverified: 2", md)
        self.assertIn("- head_sha: `0123456789ab`", md)

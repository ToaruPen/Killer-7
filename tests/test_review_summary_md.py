from __future__ import annotations

import unittest

from killer_7.report.format_md import format_review_summary_md


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

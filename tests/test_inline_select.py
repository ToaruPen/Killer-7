from __future__ import annotations

import unittest


class TestInlineSelect(unittest.TestCase):
    def test_selects_only_p0_p1_and_marks_eligible(self) -> None:
        from killer_7.github.inline_select import select_inline_candidates

        summary = {
            "findings": [
                {
                    "title": "blocking",
                    "body": "must fix",
                    "priority": "P0",
                    "sources": ["src/app.py#L11-L11"],
                    "code_location": {
                        "repo_relative_path": "src/app.py",
                        "line_range": {"start": 11, "end": 11},
                    },
                },
                {
                    "title": "nit",
                    "body": "later",
                    "priority": "P2",
                    "sources": ["src/app.py#L2-L2"],
                    "code_location": {
                        "repo_relative_path": "src/app.py",
                        "line_range": {"start": 2, "end": 2},
                    },
                },
            ]
        }

        candidates = select_inline_candidates(
            summary,
            line_map={"src/app.py": {11: 6}},
        )

        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.title, "blocking")
        self.assertEqual(c.priority, "P0")
        self.assertTrue(c.inline_eligible)
        self.assertEqual(c.diff_position, 6)
        self.assertEqual(c.skip_reason, "")
        self.assertTrue(c.fingerprint.startswith("k7f1:"))

    def test_marks_candidate_unmappable_when_line_not_found(self) -> None:
        from killer_7.github.inline_select import select_inline_candidates

        summary = {
            "findings": [
                {
                    "title": "high",
                    "body": "needs location",
                    "priority": "P1",
                    "sources": ["src/app.py#L77-L77"],
                    "code_location": {
                        "repo_relative_path": "src/app.py",
                        "line_range": {"start": 77, "end": 77},
                    },
                }
            ]
        }

        candidates = select_inline_candidates(summary, line_map={"src/app.py": {11: 6}})

        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertFalse(c.inline_eligible)
        self.assertIsNone(c.diff_position)
        self.assertEqual(c.skip_reason, "line_not_mapped")

    def test_marks_candidate_invalid_location_when_path_or_line_is_missing(
        self,
    ) -> None:
        from killer_7.github.inline_select import select_inline_candidates

        summary = {
            "findings": [
                {
                    "title": "high",
                    "body": "needs location",
                    "priority": "P1",
                    "sources": ["src/app.py#L77-L77"],
                    "code_location": {
                        "repo_relative_path": "",
                        "line_range": {"start": 0, "end": 77},
                    },
                }
            ]
        }

        candidates = select_inline_candidates(summary, line_map={})

        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertFalse(c.inline_eligible)
        self.assertEqual(c.skip_reason, "invalid_code_location")


if __name__ == "__main__":
    raise SystemExit(unittest.main())

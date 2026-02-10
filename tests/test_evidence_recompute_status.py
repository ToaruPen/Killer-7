from __future__ import annotations

import unittest


class TestEvidenceRecomputeStatus(unittest.TestCase):
    def test_question_when_questions_present(self) -> None:
        from killer_7.validate.evidence import recompute_review_status

        self.assertEqual(recompute_review_status([], ["q"]), "Question")

    def test_blocked_when_p0_or_p1_present(self) -> None:
        from killer_7.validate.evidence import recompute_review_status

        self.assertEqual(
            recompute_review_status(
                [
                    {
                        "title": "t",
                        "body": "b",
                        "priority": "P1",
                        "code_location": {
                            "repo_relative_path": "a.txt",
                            "line_range": {"start": 1, "end": 1},
                        },
                    }
                ],
                [],
            ),
            "Blocked",
        )

    def test_approved_with_nits_when_only_lower_priorities(self) -> None:
        from killer_7.validate.evidence import recompute_review_status

        self.assertEqual(
            recompute_review_status(
                [
                    {
                        "title": "t",
                        "body": "b",
                        "priority": "P3",
                        "code_location": {
                            "repo_relative_path": "a.txt",
                            "line_range": {"start": 1, "end": 1},
                        },
                    }
                ],
                [],
            ),
            "Approved with nits",
        )

    def test_approved_when_no_findings_or_questions(self) -> None:
        from killer_7.validate.evidence import recompute_review_status

        self.assertEqual(recompute_review_status([], []), "Approved")


if __name__ == "__main__":
    raise SystemExit(unittest.main())

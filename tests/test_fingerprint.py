from __future__ import annotations

import unittest


class TestFingerprint(unittest.TestCase):
    def test_same_finding_produces_same_fingerprint(self) -> None:
        from killer_7.report.fingerprint import finding_fingerprint

        finding = {
            "title": "  Missing  guard  ",
            "body": "input can be None\n\n",
            "priority": "p1",
            "sources": ["src/app.py#L10-L10"],
            "code_location": {
                "repo_relative_path": "src/app.py",
                "line_range": {"start": 10, "end": 10},
            },
        }

        first = finding_fingerprint(finding)
        second = finding_fingerprint(dict(finding))

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("k7f1:"))

    def test_different_location_changes_fingerprint(self) -> None:
        from killer_7.report.fingerprint import finding_fingerprint

        finding1 = {
            "title": "Missing guard",
            "body": "input can be None",
            "priority": "P1",
            "sources": ["src/app.py#L10-L10"],
            "code_location": {
                "repo_relative_path": "src/app.py",
                "line_range": {"start": 10, "end": 10},
            },
        }
        finding2 = {
            "title": "Missing guard",
            "body": "input can be None",
            "priority": "P1",
            "sources": ["src/app.py#L11-L11"],
            "code_location": {
                "repo_relative_path": "src/app.py",
                "line_range": {"start": 11, "end": 11},
            },
        }

        self.assertNotEqual(
            finding_fingerprint(finding1), finding_fingerprint(finding2)
        )

    def test_source_order_does_not_change_fingerprint(self) -> None:
        from killer_7.report.fingerprint import finding_fingerprint

        finding1 = {
            "title": "Missing guard",
            "body": "input can be None",
            "priority": "P1",
            "sources": ["b.py#L1-L1", "a.py#L2-L2"],
            "code_location": {
                "repo_relative_path": "src/app.py",
                "line_range": {"start": 10, "end": 10},
            },
        }
        finding2 = {
            "title": "Missing guard",
            "body": "input can be None",
            "priority": "P1",
            "sources": ["a.py#L2-L2", "b.py#L1-L1"],
            "code_location": {
                "repo_relative_path": "src/app.py",
                "line_range": {"start": 10, "end": 10},
            },
        }

        self.assertEqual(finding_fingerprint(finding1), finding_fingerprint(finding2))


if __name__ == "__main__":
    raise SystemExit(unittest.main())

from __future__ import annotations

import unittest


class TestVerifyFindingEvidence(unittest.TestCase):
    def test_verified_true_when_source_path_matches_and_line_intersects(self) -> None:
        from killer_7.validate.evidence import verify_finding_evidence

        idx = {"a.txt": {1, 2, 10}, "b.txt": {5}}
        finding = {
            "title": "t",
            "body": "b",
            "priority": "P0",
            "sources": ["a.txt"],
            "code_location": {
                "repo_relative_path": "a.txt",
                "line_range": {"start": 9, "end": 11},
            },
        }

        verified, reason = verify_finding_evidence(finding, idx)
        self.assertTrue(verified)
        self.assertEqual(reason, "")

    def test_verified_true_when_source_includes_line_range(self) -> None:
        from killer_7.validate.evidence import verify_finding_evidence

        idx = {"a.txt": {1, 2, 10, 11}}
        finding = {
            "title": "t",
            "body": "b",
            "priority": "P0",
            "sources": ["a.txt#L10-L11"],
            "code_location": {
                "repo_relative_path": "a.txt",
                "line_range": {"start": 9, "end": 20},
            },
        }

        verified, reason = verify_finding_evidence(finding, idx)
        self.assertTrue(verified)
        self.assertEqual(reason, "")

    def test_unverified_when_sources_missing(self) -> None:
        from killer_7.validate.evidence import verify_finding_evidence

        idx = {"a.txt": {1}}
        finding = {
            "title": "t",
            "body": "b",
            "priority": "P0",
            "code_location": {
                "repo_relative_path": "a.txt",
                "line_range": {"start": 1, "end": 1},
            },
        }

        verified, reason = verify_finding_evidence(finding, idx)
        self.assertFalse(verified)
        self.assertEqual(reason, "missing_sources")

    def test_unverified_when_sources_present_but_malformed(self) -> None:
        from killer_7.validate.evidence import verify_finding_evidence

        idx = {"a.txt": {1}}
        finding = {
            "title": "t",
            "body": "b",
            "priority": "P0",
            "sources": ["a.txt#Lx"],
            "code_location": {
                "repo_relative_path": "a.txt",
                "line_range": {"start": 1, "end": 1},
            },
        }

        verified, reason = verify_finding_evidence(finding, idx)
        self.assertFalse(verified)
        self.assertEqual(reason, "invalid_sources")

    def test_unverified_when_source_not_resolved_to_any_src(self) -> None:
        from killer_7.validate.evidence import verify_finding_evidence

        idx = {"a.txt": {1}}
        finding = {
            "title": "t",
            "body": "b",
            "priority": "P1",
            "sources": ["missing.txt"],
            "code_location": {
                "repo_relative_path": "a.txt",
                "line_range": {"start": 1, "end": 1},
            },
        }

        verified, reason = verify_finding_evidence(finding, idx)
        self.assertFalse(verified)
        self.assertEqual(reason, "unresolved_source")

    def test_unverified_when_source_resolves_but_points_to_other_path(self) -> None:
        from killer_7.validate.evidence import verify_finding_evidence

        idx = {"a.txt": {1}, "b.txt": {1}}
        finding = {
            "title": "t",
            "body": "b",
            "priority": "P2",
            "sources": ["b.txt"],
            "code_location": {
                "repo_relative_path": "a.txt",
                "line_range": {"start": 1, "end": 1},
            },
        }

        verified, reason = verify_finding_evidence(finding, idx)
        self.assertFalse(verified)
        self.assertEqual(reason, "path_mismatch")

    def test_unverified_when_line_not_in_context_bundle(self) -> None:
        from killer_7.validate.evidence import verify_finding_evidence

        idx = {"a.txt": {1, 2, 3}}
        finding = {
            "title": "t",
            "body": "b",
            "priority": "P0",
            "sources": ["a.txt"],
            "code_location": {
                "repo_relative_path": "a.txt",
                "line_range": {"start": 10, "end": 20},
            },
        }

        verified, reason = verify_finding_evidence(finding, idx)
        self.assertFalse(verified)
        self.assertEqual(reason, "line_mismatch")

    def test_unverified_when_src_has_no_line_index(self) -> None:
        from killer_7.validate.evidence import verify_finding_evidence

        # Path exists (e.g., SoT section), but no L<line> markers.
        idx = {"a.txt": set[int]()}
        finding = {
            "title": "t",
            "body": "b",
            "priority": "P1",
            "sources": ["a.txt"],
            "code_location": {
                "repo_relative_path": "a.txt",
                "line_range": {"start": 1, "end": 1},
            },
        }

        verified, reason = verify_finding_evidence(finding, idx)
        self.assertFalse(verified)
        self.assertEqual(reason, "line_unverifiable")


if __name__ == "__main__":
    raise SystemExit(unittest.main())

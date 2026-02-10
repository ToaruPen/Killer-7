from __future__ import annotations

import unittest


class TestEvidencePolicyApply(unittest.TestCase):
    def test_excludes_or_downgrades_unverified_strong_findings(self) -> None:
        from killer_7.validate.evidence import apply_evidence_policy_to_findings

        context_index = {
            "a.txt": {10},
        }

        findings: list[object] = [
            {
                "title": "verified p0",
                "body": "b",
                "priority": "P0",
                "sources": ["a.txt"],
                "code_location": {
                    "repo_relative_path": "a.txt",
                    "line_range": {"start": 9, "end": 11},
                },
            },
            {
                "title": "missing sources p0",
                "body": "b",
                "priority": "P0",
                "code_location": {
                    "repo_relative_path": "a.txt",
                    "line_range": {"start": 1, "end": 1},
                },
            },
            {
                "title": "invalid sources p0",
                "body": "b",
                "priority": "P0",
                "sources": ["a.txt#Lx"],
                "code_location": {
                    "repo_relative_path": "a.txt",
                    "line_range": {"start": 1, "end": 1},
                },
            },
            {
                "title": "unresolved source p1",
                "body": "b",
                "priority": "P1",
                "sources": ["missing.txt"],
                "code_location": {
                    "repo_relative_path": "a.txt",
                    "line_range": {"start": 10, "end": 10},
                },
            },
            {
                "title": "line mismatch p2",
                "body": "b",
                "priority": "P2",
                "sources": ["a.txt"],
                "code_location": {
                    "repo_relative_path": "a.txt",
                    "line_range": {"start": 1, "end": 2},
                },
            },
            {
                "title": "unverified p3",
                "body": "b",
                "priority": "P3",
                "sources": ["a.txt"],
                "code_location": {
                    "repo_relative_path": "a.txt",
                    "line_range": {"start": 1, "end": 2},
                },
            },
        ]

        out_findings, stats = apply_evidence_policy_to_findings(findings, context_index)

        # AC1 intent: no unverified P0/P1 remain.
        for f in out_findings:
            pr = f.get("priority")
            verified = f.get("verified")
            if pr in ("P0", "P1"):
                self.assertEqual(verified, True)

        titles = {f.get("title") for f in out_findings}
        self.assertIn("verified p0", titles)
        self.assertNotIn("missing sources p0", titles)

        invalid = [f for f in out_findings if f.get("title") == "invalid sources p0"][0]
        self.assertEqual(invalid.get("priority"), "P3")
        self.assertEqual(invalid.get("original_priority"), "P0")
        self.assertEqual(invalid.get("verified"), False)

        unresolved = [
            f for f in out_findings if f.get("title") == "unresolved source p1"
        ][0]
        self.assertEqual(unresolved.get("priority"), "P3")
        self.assertEqual(unresolved.get("original_priority"), "P1")
        self.assertEqual(unresolved.get("verified"), False)

        mismatch = [f for f in out_findings if f.get("title") == "line mismatch p2"][0]
        self.assertEqual(mismatch.get("priority"), "P3")
        self.assertEqual(mismatch.get("original_priority"), "P2")
        self.assertEqual(mismatch.get("verified"), False)

        p3 = [f for f in out_findings if f.get("title") == "unverified p3"][0]
        self.assertEqual(p3.get("priority"), "P3")
        self.assertEqual(p3.get("verified"), False)
        self.assertTrue("original_priority" not in p3)

        self.assertEqual(stats.get("excluded_count"), 1)
        self.assertEqual(stats.get("downgraded_count"), 3)

    def test_policy_plus_status_recompute_drops_unverified_blockers(self) -> None:
        from killer_7.validate.evidence import (
            apply_evidence_policy_to_findings,
            recompute_review_status,
        )

        context_index = {
            "a.txt": {10},
        }

        findings: list[object] = [
            {
                "title": "missing sources p0",
                "body": "b",
                "priority": "P0",
                "code_location": {
                    "repo_relative_path": "a.txt",
                    "line_range": {"start": 1, "end": 1},
                },
            },
            {
                "title": "unresolved source p1",
                "body": "b",
                "priority": "P1",
                "sources": ["missing.txt"],
                "code_location": {
                    "repo_relative_path": "a.txt",
                    "line_range": {"start": 10, "end": 10},
                },
            },
        ]

        out_findings, _stats = apply_evidence_policy_to_findings(
            findings, context_index
        )
        self.assertEqual(
            recompute_review_status(out_findings, []), "Approved with nits"
        )


if __name__ == "__main__":
    raise SystemExit(unittest.main())

from __future__ import annotations

import unittest

from killer_7.errors import ExecFailureError


class TestHybridPolicy(unittest.TestCase):
    def test_default_policy_disables_repo_access(self) -> None:
        from killer_7.hybrid.policy import build_hybrid_policy

        p = build_hybrid_policy(hybrid_aspects=[], hybrid_allowlist=[])
        d = p.decision_for(aspect="correctness")

        self.assertFalse(d.repo_read_only)
        self.assertEqual(d.allowlist_paths, ())

    def test_specific_aspects_enable_repo_access_with_allowlist(self) -> None:
        from killer_7.hybrid.policy import build_hybrid_policy

        p = build_hybrid_policy(
            hybrid_aspects=["Correctness", "security"],
            hybrid_allowlist=["docs/**/*.md", "killer_7/**/*.py"],
        )

        d1 = p.decision_for(aspect="correctness")
        self.assertTrue(d1.repo_read_only)
        self.assertEqual(d1.allowlist_paths, ("docs/**/*.md", "killer_7/**/*.py"))

        d2 = p.decision_for(aspect="readability")
        self.assertFalse(d2.repo_read_only)
        self.assertEqual(d2.allowlist_paths, ())

    def test_hybrid_aspects_without_allowlist_do_not_enable_repo_access(self) -> None:
        from killer_7.hybrid.policy import build_hybrid_policy

        p = build_hybrid_policy(
            hybrid_aspects=["correctness"],
            hybrid_allowlist=[],
        )

        d = p.decision_for(aspect="correctness")
        self.assertFalse(d.repo_read_only)
        self.assertEqual(d.allowlist_paths, ())

    def test_rejects_parent_traversal_pattern(self) -> None:
        from killer_7.hybrid.policy import build_hybrid_policy

        with self.assertRaises(ExecFailureError):
            build_hybrid_policy(
                hybrid_aspects=["correctness"],
                hybrid_allowlist=["../**/*"],
            )

    def test_rejects_newline_in_allowlist_pattern(self) -> None:
        from killer_7.hybrid.policy import build_hybrid_policy

        with self.assertRaises(ExecFailureError):
            build_hybrid_policy(
                hybrid_aspects=["correctness"],
                hybrid_allowlist=["docs/**\n../**/*"],
            )

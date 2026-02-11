from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class TestHybridReRun(unittest.TestCase):
    def test_writes_rerun_artifacts_for_question_aspects(self) -> None:
        from killer_7.hybrid.re_run import write_questions_rerun_artifacts

        with tempfile.TemporaryDirectory() as td:
            out = write_questions_rerun_artifacts(
                out_dir=str(Path(td) / ".ai-review"),
                repo="owner/name",
                pr=123,
                head_sha="0123456789abcdef",
                question_aspects=["correctness", "security"],
                hybrid_allowlist=["docs/**/*.md"],
            )

            plan_path = Path(str(out["plan_path"]))
            self.assertTrue(plan_path.is_file())
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["question_aspects"], ["correctness", "security"])
            self.assertIn(
                "--hybrid-aspect correctness --hybrid-aspect security",
                payload["recommended_command"],
            )
            self.assertIn(
                "--hybrid-allowlist 'docs/**/*.md'",
                payload["recommended_command"],
            )
            self.assertIn(".ai-review/re-run/", payload["output_dir"])

    def test_output_dir_is_stable_relative_to_base_dir(self) -> None:
        from killer_7.hybrid.re_run import write_questions_rerun_artifacts

        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            out_dir = work / ".ai-review"
            other_cwd = work / "other"
            other_cwd.mkdir(parents=True)

            prev_cwd = os.getcwd()
            try:
                os.chdir(str(other_cwd))
                out = write_questions_rerun_artifacts(
                    out_dir=str(out_dir),
                    repo="owner/name",
                    pr=123,
                    head_sha="0123456789abcdef",
                    question_aspects=["correctness"],
                    hybrid_allowlist=["docs/**/*.md"],
                )
            finally:
                os.chdir(prev_cwd)

            plan_path = Path(str(out["plan_path"]))
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertIn(".ai-review/re-run/", payload["output_dir"])

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from killer_7.errors import ExecFailureError
from killer_7.github.reviewdog import run_reviewdog_from_sarif


class TestReviewdog(unittest.TestCase):
    def test_run_reviewdog_uses_configured_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sarif_path = Path(td) / "review-summary.sarif.json"
            sarif_path.write_text('{"version":"2.1.0","runs":[]}', encoding="utf-8")

            completed = subprocess.CompletedProcess(
                args=["reviewdog"], returncode=0, stdout="", stderr=""
            )
            with patch.dict(os.environ, {"KILLER7_REVIEWDOG_TIMEOUT_S": "7"}):
                with patch(
                    "killer_7.github.reviewdog.subprocess.run", return_value=completed
                ) as run_mock:
                    run_reviewdog_from_sarif(
                        sarif_path=str(sarif_path), reporter="github-pr-review"
                    )

            self.assertEqual(run_mock.call_args.kwargs.get("timeout"), 7)

    def test_run_reviewdog_timeout_is_exec_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sarif_path = Path(td) / "review-summary.sarif.json"
            sarif_path.write_text('{"version":"2.1.0","runs":[]}', encoding="utf-8")

            with patch.dict(os.environ, {"KILLER7_REVIEWDOG_TIMEOUT_S": "3"}):
                with patch(
                    "killer_7.github.reviewdog.subprocess.run",
                    side_effect=subprocess.TimeoutExpired(cmd=["reviewdog"], timeout=3),
                ):
                    with self.assertRaisesRegex(
                        ExecFailureError, "reviewdog timed out after 3s"
                    ):
                        run_reviewdog_from_sarif(
                            sarif_path=str(sarif_path), reporter="github-pr-review"
                        )

    def test_run_reviewdog_missing_binary_is_exec_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sarif_path = Path(td) / "review-summary.sarif.json"
            sarif_path.write_text('{"version":"2.1.0","runs":[]}', encoding="utf-8")

            with patch(
                "killer_7.github.reviewdog.subprocess.run",
                side_effect=FileNotFoundError("not found"),
            ):
                with self.assertRaisesRegex(
                    ExecFailureError, "reviewdog binary not found: reviewdog"
                ):
                    run_reviewdog_from_sarif(
                        sarif_path=str(sarif_path), reporter="github-pr-review"
                    )


if __name__ == "__main__":
    unittest.main()

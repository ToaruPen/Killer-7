from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestValidateReviewJsonScript(unittest.TestCase):
    def test_accepts_valid_payload(self) -> None:
        here = Path(__file__).resolve().parents[1]
        script = here / "scripts" / "validate-review-json.py"

        payload = {
            "schema_version": 3,
            "scope_id": "scope-1",
            "status": "Blocked",
            "findings": [
                {
                    "title": "t",
                    "body": "b",
                    "priority": "P0",
                    "code_location": {
                        "repo_relative_path": "a.txt",
                        "line_range": {"start": 1, "end": 2},
                    },
                }
            ],
            "questions": [],
            "overall_explanation": "ok",
        }

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "review.json"
            p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            proc = subprocess.run(  # noqa: S603
                [sys.executable, str(script), str(p), "--scope-id", "scope-1"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=(proc.stdout + "\n" + proc.stderr))


if __name__ == "__main__":
    raise SystemExit(unittest.main())

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from killer_7.errors import ExecFailureError


class _FakeRunner:
    def __init__(self, *, payload: object) -> None:
        self.payload = payload

    def run_viewpoint(
        self,
        *,
        out_dir: str,
        viewpoint: str,
        message: str,
        timeout_s: int | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        _ = (out_dir, viewpoint, message, timeout_s, env)
        return {
            "viewpoint": viewpoint,
            "result_path": "<fake>",
            "payload": self.payload,
        }


class TestRunOneAspect(unittest.TestCase):
    def test_success_writes_aspect_json(self) -> None:
        from killer_7.aspects.run_one import run_one_aspect

        with tempfile.TemporaryDirectory() as td:
            runner = _FakeRunner(
                payload={
                    "schema_version": 3,
                    "scope_id": "scope-1",
                    "status": "Approved",
                    "findings": [],
                    "questions": [],
                    "overall_explanation": "ok",
                }
            )
            res = run_one_aspect(
                base_dir=td,
                aspect="correctness",
                scope_id="scope-1",
                context_bundle="CTX",
                runner=runner,
            )

            p = Path(str(res["aspect_result_path"]))
            self.assertTrue(p.is_file())
            payload = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 3)
            self.assertEqual(payload["scope_id"], "scope-1")
            self.assertIn("status", payload)
            self.assertIn("findings", payload)
            self.assertIn("questions", payload)
            self.assertIn("overall_explanation", payload)

    def test_invalid_output_missing_required_keys_raises(self) -> None:
        from killer_7.aspects.run_one import run_one_aspect

        with tempfile.TemporaryDirectory() as td:
            runner = _FakeRunner(
                payload={
                    "schema_version": 3,
                    "scope_id": "scope-1",
                    "status": "Approved",
                    "findings": [],
                    "questions": [],
                }
            )
            with self.assertRaises(ExecFailureError):
                run_one_aspect(
                    base_dir=td,
                    aspect="correctness",
                    scope_id="scope-1",
                    context_bundle="CTX",
                    runner=runner,
                )

            out = Path(td) / ".ai-review" / "aspects" / "correctness.json"
            self.assertFalse(out.exists())

            err = Path(td) / ".ai-review" / "errors" / "correctness.schema.error.json"
            self.assertTrue(err.is_file())
            payload = json.loads(err.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("schema_version"), 1)
            self.assertEqual(payload.get("kind"), "schema_validation_failed")
            self.assertEqual(payload.get("aspect"), "correctness")
            self.assertEqual(
                payload.get("target_path"), ".ai-review/aspects/correctness.json"
            )
            self.assertTrue(isinstance(payload.get("errors"), list))

    def test_accepts_finding_sources(self) -> None:
        from killer_7.aspects.run_one import run_one_aspect

        with tempfile.TemporaryDirectory() as td:
            runner = _FakeRunner(
                payload={
                    "schema_version": 3,
                    "scope_id": "scope-1",
                    "status": "Blocked",
                    "findings": [
                        {
                            "title": "t",
                            "body": "b",
                            "priority": "P0",
                            "sources": ["a.txt#L1-L2"],
                            "code_location": {
                                "repo_relative_path": "a.txt",
                                "line_range": {"start": 1, "end": 2},
                            },
                        }
                    ],
                    "questions": [],
                    "overall_explanation": "ok",
                }
            )
            res = run_one_aspect(
                base_dir=td,
                aspect="correctness",
                scope_id="scope-1",
                context_bundle="CTX",
                runner=runner,
            )

            self.assertEqual(res["aspect"], "correctness")
            self.assertEqual(res["scope_id"], "scope-1")
            p = Path(str(res["aspect_result_path"]))
            self.assertTrue(p.is_file())

            payload = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("schema_version"), 3)
            self.assertEqual(payload.get("scope_id"), "scope-1")
            self.assertEqual(payload.get("status"), "Blocked")
            findings = payload.get("findings")
            self.assertTrue(isinstance(findings, list))
            self.assertEqual(findings[0].get("sources"), ["a.txt#L1-L2"])


if __name__ == "__main__":
    raise SystemExit(unittest.main())

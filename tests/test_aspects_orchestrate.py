from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from killer_7.errors import ExecFailureError


class _FakeRunner:
    def __init__(self, *, payload_by_viewpoint: Mapping[str, object]) -> None:
        self.payload_by_viewpoint = dict(payload_by_viewpoint)
        self.seen_env_by_viewpoint: dict[str, dict[str, str] | None] = {}
        self.seen_message_by_viewpoint: dict[str, str] = {}

    def run_viewpoint(
        self,
        *,
        out_dir: str,
        viewpoint: str,
        message: str,
        timeout_s: int | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        _ = (out_dir, timeout_s, env)
        self.seen_env_by_viewpoint[viewpoint] = env
        self.seen_message_by_viewpoint[viewpoint] = message
        payload = self.payload_by_viewpoint.get(viewpoint)
        if payload is None:
            payload = {
                "schema_version": 3,
                "scope_id": "scope-1",
                "status": "Approved",
                "findings": [],
                "questions": [],
                "overall_explanation": "ok",
            }
        return {
            "viewpoint": viewpoint,
            "result_path": "<fake>",
            "payload": payload,
        }


class TestOrchestrate(unittest.TestCase):
    def test_success_writes_index_and_aspect_jsons(self) -> None:
        from killer_7.aspects.orchestrate import ASPECTS_V1, run_all_aspects

        payload: dict[str, object] = {
            "schema_version": 3,
            "scope_id": "scope-1",
            "status": "Approved",
            "findings": [],
            "questions": [],
            "overall_explanation": "ok",
        }

        with tempfile.TemporaryDirectory() as td:
            res = run_all_aspects(
                base_dir=td,
                scope_id="scope-1",
                context_bundle="CTX",
                sot="SOT",
                runner_factory=lambda: _FakeRunner(
                    payload_by_viewpoint={a: payload for a in ASPECTS_V1}
                ),
            )

            out_dir = Path(td) / ".ai-review" / "aspects"
            self.assertTrue((out_dir / "index.json").is_file())
            for a in ASPECTS_V1:
                self.assertTrue((out_dir / f"{a}.json").is_file())

            idx = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(idx["schema_version"], 1)
            self.assertEqual(idx["scope_id"], "scope-1")
            self.assertEqual(len(idx["aspects"]), len(ASPECTS_V1))
            self.assertTrue(all(x["ok"] for x in idx["aspects"]))
            self.assertEqual(str(res["index_path"]), str(out_dir / "index.json"))

    def test_partial_failure_writes_error_and_exits_failure(self) -> None:
        from killer_7.aspects.orchestrate import ASPECTS_V1, run_all_aspects

        good: dict[str, object] = {
            "schema_version": 3,
            "scope_id": "scope-1",
            "status": "Approved",
            "findings": [],
            "questions": [],
            "overall_explanation": "ok",
        }
        bad: dict[str, object] = {
            "schema_version": 3,
            "scope_id": "scope-1",
            "status": "Approved",
            "findings": [],
            "questions": [],
            # overall_explanation is required
        }

        payloads: dict[str, object] = {a: good for a in ASPECTS_V1}
        payloads["security"] = bad

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ExecFailureError):
                run_all_aspects(
                    base_dir=td,
                    scope_id="scope-1",
                    context_bundle="CTX",
                    sot="SOT",
                    runner_factory=lambda: _FakeRunner(payload_by_viewpoint=payloads),
                )

            out_dir = Path(td) / ".ai-review" / "aspects"
            self.assertTrue((out_dir / "index.json").is_file())
            self.assertTrue((out_dir / "security.error.json").is_file())

            err_dir = Path(td) / ".ai-review" / "errors"
            # Schema validation failures are expected to be written by run_one_aspect.
            self.assertTrue((err_dir / "security.schema.error.json").is_file())
            self.assertFalse((err_dir / "security.exec_failure.error.json").exists())
            idx = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
            failed = [x for x in idx["aspects"] if x["aspect"] == "security"]
            self.assertEqual(len(failed), 1)
            self.assertFalse(failed[0]["ok"])

    def test_passes_runner_env_per_aspect(self) -> None:
        from killer_7.aspects.orchestrate import ASPECTS_V1, run_all_aspects

        payload: dict[str, object] = {
            "schema_version": 3,
            "scope_id": "scope-1",
            "status": "Approved",
            "findings": [],
            "questions": [],
            "overall_explanation": "ok",
        }

        runners: list[_FakeRunner] = []

        def make_runner() -> _FakeRunner:
            r = _FakeRunner(payload_by_viewpoint={a: payload for a in ASPECTS_V1})
            runners.append(r)
            return r

        def env_for_aspect(aspect: str) -> dict[str, str]:
            if aspect == "correctness":
                return {
                    "KILLER7_REPO_READONLY": "1",
                    "KILLER7_REPO_ALLOWLIST": "docs/**/*.md",
                }
            return {"KILLER7_REPO_READONLY": "0"}

        with tempfile.TemporaryDirectory() as td:
            run_all_aspects(
                base_dir=td,
                scope_id="scope-1",
                context_bundle="CTX",
                sot="SOT",
                runner_factory=make_runner,
                runner_env_for_aspect=env_for_aspect,
            )

        seen: dict[str, dict[str, str] | None] = {}
        for r in runners:
            seen.update(r.seen_env_by_viewpoint)

        self.assertEqual(
            seen["correctness"],
            {
                "KILLER7_REPO_READONLY": "1",
                "KILLER7_REPO_ALLOWLIST": "docs/**/*.md",
            },
        )
        self.assertEqual(seen["readability"], {"KILLER7_REPO_READONLY": "0"})

    def test_rejects_unknown_aspects_as_input_error(self) -> None:
        from killer_7.aspects.orchestrate import run_all_aspects

        payload: dict[str, object] = {
            "schema_version": 3,
            "scope_id": "scope-1",
            "status": "Approved",
            "findings": [],
            "questions": [],
            "overall_explanation": "ok",
        }

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ExecFailureError):
                run_all_aspects(
                    base_dir=td,
                    scope_id="scope-1",
                    context_bundle="CTX",
                    sot="SOT",
                    aspects=("correctness", "unknown"),
                    runner_factory=lambda: _FakeRunner(
                        payload_by_viewpoint={"correctness": payload}
                    ),
                )

            err = Path(td) / ".ai-review" / "errors" / "aspects.input.error.json"
            self.assertTrue(err.is_file())

    def test_can_disable_sot_for_specific_aspect(self) -> None:
        from killer_7.aspects.orchestrate import run_all_aspects

        payload: dict[str, object] = {
            "schema_version": 3,
            "scope_id": "scope-1",
            "status": "Approved",
            "findings": [],
            "questions": [],
            "overall_explanation": "ok",
        }

        runner = _FakeRunner(
            payload_by_viewpoint={"correctness": payload, "performance": payload}
        )

        def make_runner() -> _FakeRunner:
            return runner

        with tempfile.TemporaryDirectory() as td:
            run_all_aspects(
                base_dir=td,
                scope_id="scope-1",
                context_bundle="CTX",
                sot="SOT_MARKER_X",
                aspects=("correctness", "performance"),
                runner_factory=make_runner,
                sot_for_aspect=lambda aspect: (
                    "" if aspect == "performance" else "SOT_MARKER_X"
                ),
            )

        self.assertIn("SOT_MARKER_X", runner.seen_message_by_viewpoint["correctness"])
        self.assertNotIn(
            "SOT_MARKER_X", runner.seen_message_by_viewpoint["performance"]
        )


if __name__ == "__main__":
    raise SystemExit(unittest.main())

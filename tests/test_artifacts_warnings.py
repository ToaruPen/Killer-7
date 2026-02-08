from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class TestArtifactsWarnings(unittest.TestCase):
    def test_writes_allowlist_paths_and_content_warnings_json(self) -> None:
        from killer_7.artifacts import (
            ensure_artifacts_dir,
            write_allowlist_paths_json,
            write_content_warnings_json,
        )
        from killer_7.github.content import ContentWarning

        with tempfile.TemporaryDirectory() as td:
            out_dir = ensure_artifacts_dir(td)

            paths = ["README.md", "docs/a.md"]
            warnings: list[object] = [
                ContentWarning(
                    kind="size_limit_exceeded",
                    path="docs/big.txt",
                    message="Skipped file because it exceeds max_bytes",
                    size_bytes=200000,
                    limit_bytes=102400,
                )
            ]

            paths_file = write_allowlist_paths_json(out_dir, paths)
            warnings_file = write_content_warnings_json(out_dir, warnings)

            self.assertTrue(Path(paths_file).is_file())
            self.assertTrue(Path(warnings_file).is_file())

            paths_payload = json.loads(Path(paths_file).read_text(encoding="utf-8"))
            self.assertEqual(paths_payload["schema_version"], 1)
            self.assertEqual(paths_payload["paths"], paths)

            warn_payload = json.loads(Path(warnings_file).read_text(encoding="utf-8"))
            self.assertEqual(warn_payload["schema_version"], 1)
            self.assertEqual(warn_payload["warnings"][0]["path"], "docs/big.txt")

    def test_write_validation_error_json_sanitizes_filename(self) -> None:
        from killer_7.artifacts import ensure_artifacts_dir, write_validation_error_json

        with tempfile.TemporaryDirectory() as td:
            out_dir = ensure_artifacts_dir(td)
            p = write_validation_error_json(
                out_dir,
                filename="../escape.json",
                kind="schema_validation_failed",
                message="bad",
                target_path=".ai-review/aspects/x.json",
                errors=["missing keys: ['overall_explanation']"],
                extra={"aspect": "x"},
            )

            path = Path(p)
            self.assertTrue(path.is_file())
            self.assertEqual(path.name, "escape.json")
            self.assertEqual(path.parent.name, "errors")

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["kind"], "schema_validation_failed")
            self.assertIn("original_filename", payload)


if __name__ == "__main__":
    raise SystemExit(unittest.main())

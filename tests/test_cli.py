from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_fake_gh(path: Path) -> None:
    """Write a tiny fake `gh` binary for tests."""

    path.write_text(
        """#!/usr/bin/env python3
import base64
import json
import sys

args = sys.argv[1:]


def has(flag: str) -> bool:
    return flag in args


if args[:2] == ["pr", "diff"]:
    # gh pr diff <pr> --repo owner/name --patch
    def emit_new_file(path: str, n_lines: int, *, first_line=None) -> None:
        sys.stdout.write(f"diff --git a/{path} b/{path}\\n")
        sys.stdout.write("new file mode 100644\\n")
        sys.stdout.write("index 0000000..1111111\\n")
        sys.stdout.write("--- /dev/null\\n")
        sys.stdout.write(f"+++ b/{path}\\n")
        if n_lines == 1:
            sys.stdout.write("@@ -0,0 +1 @@\\n")
        else:
            sys.stdout.write(f"@@ -0,0 +1,{n_lines} @@\\n")
        for i in range(1, n_lines + 1):
            if i == 1 and first_line is not None:
                sys.stdout.write(f"+{first_line}\\n")
            else:
                sys.stdout.write(f"+{path}-line-{i}\\n")

    # A small diff that must be included.
    emit_new_file("hello.txt", 1, first_line="hello")

    # Large blocks to saturate the diff budget and force total truncation.
    emit_new_file("big1.txt", 399)
    emit_new_file("big2.txt", 399)
    emit_new_file("big3.txt", 399)
    emit_new_file("big4.txt", 399)

    # A later small block that should still be included (skip-and-continue).
    emit_new_file("tail.txt", 47)

    # A per-file overflow block (should be dropped, but still emit a warning).
    emit_new_file("huge.txt", 401)
    raise SystemExit(0)


if args[:2] == ["pr", "view"]:
    # gh pr view <pr> --repo owner/name --json headRefOid
    sys.stdout.write(json.dumps({"headRefOid": "0123456789abcdef"}))
    raise SystemExit(0)


if args[:1] == ["api"]:
    # gh api [flags...] <endpoint>
    endpoint = args[-1]
    if endpoint.endswith("/pulls/123/files"):
        files = [
            {
                "filename": "hello.txt",
                "status": "added",
                "additions": 1,
                "deletions": 0,
            },
            {
                "filename": "old.txt",
                "status": "removed",
                "additions": 0,
                "deletions": 10,
            },
            {
                "filename": "newname.txt",
                "previous_filename": "oldname.txt",
                "status": "renamed",
                "additions": 0,
                "deletions": 0,
            },
        ]

        if has("--slurp"):
            sys.stdout.write(json.dumps([files]))
        else:
            sys.stdout.write(json.dumps(files))
        raise SystemExit(0)

    if "/commits/" in endpoint:
        sys.stdout.write(json.dumps({"commit": {"tree": {"sha": "TREE123"}}}))
        raise SystemExit(0)

    if "/git/trees/" in endpoint:
        sys.stdout.write(
            json.dumps(
                {
                    "truncated": False,
                    "tree": [
                        {
                            "path": "docs/prd/killer-7.md",
                            "type": "blob",
                            "sha": "B1",
                            "size": 10,
                        },
                        {
                            "path": "docs/decisions.md",
                            "type": "blob",
                            "sha": "B2",
                            "size": 10,
                        },
                    ],
                }
            )
        )
        raise SystemExit(0)

    if "/contents/" in endpoint:
        # Provide one large markdown to force SoT truncation.
        if endpoint.endswith("/contents/docs/prd/killer-7.md?ref=0123456789abcdef"):
            text = ("line\\n" * 400).encode("utf-8")
            sys.stdout.write(
                json.dumps(
                    {
                        "type": "file",
                        "encoding": "base64",
                        "size": len(text),
                        "path": "docs/prd/killer-7.md",
                        "content": base64.b64encode(text).decode("ascii"),
                    }
                )
            )
            raise SystemExit(0)

        # Simulate fetch failure for decisions.md (should become a warning, not a crash).
        if endpoint.endswith("/contents/docs/decisions.md?ref=0123456789abcdef"):
            sys.stderr.write("Not Found\\n")
            raise SystemExit(1)


sys.stderr.write("fake gh: unsupported args: " + " ".join(args) + "\\n")
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode(path: Path) -> None:
    """Write a tiny fake `opencode` binary for tests.

    The real implementation expects JSONL events (one per line) and extracts the last
    `type=text` event's `part.text` as JSON.
    """

    path.write_text(
        """#!/usr/bin/env python3
import json
import re
import sys

args = sys.argv[1:]

if args[:1] != ["run"]:
    sys.stderr.write("fake opencode: unsupported args: " + " ".join(args) + "\\n")
    raise SystemExit(2)

prompt = sys.stdin.read()
m = re.search("^Scope ID:\\s*(.+)\\s*$", prompt, flags=re.M)
scope_id = m.group(1).strip() if m else "scope-unknown"

payload = {
  "schema_version": 3,
  "scope_id": scope_id,
  "status": "Approved",
  "findings": [],
  "questions": [],
  "overall_explanation": "ok",
}

event = {"type": "text", "part": {"text": json.dumps(payload)}}
sys.stdout.write(json.dumps(event) + "\\n")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def run_cli(
    args: list[str],
    cwd: str,
    *,
    gh_bin: str | None = None,
    opencode_bin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    if gh_bin is not None:
        env["KILLER7_GH_BIN"] = gh_bin
    if opencode_bin is not None:
        env["KILLER7_OPENCODE_BIN"] = opencode_bin
    return subprocess.run(
        [sys.executable, "-m", "killer_7.cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class TestCli(unittest.TestCase):
    def test_invalid_args_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = run_cli(["review", "--repo", "owner/name"], cwd=td)
            self.assertEqual(p.returncode, 2)

    def test_creates_artifacts_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0)

            run_json = Path(td) / ".ai-review" / "run.json"
            self.assertTrue(run_json.is_file())

            payload = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["exit_code"], 0)
            self.assertEqual(payload["status"], "ok")

    def test_creates_sot_bundle_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            out_dir = Path(td) / ".ai-review"
            sot_md = out_dir / "sot.md"
            warnings_txt = out_dir / "warnings.txt"
            context_bundle = out_dir / "context-bundle.txt"
            self.assertTrue(sot_md.is_file())
            self.assertTrue(warnings_txt.is_file())
            self.assertTrue(context_bundle.is_file())

            sot_text = sot_md.read_text(encoding="utf-8")
            self.assertIn("# SRC: docs/prd/killer-7.md", sot_text)
            self.assertIn("L1: ", sot_text)
            self.assertLessEqual(len(sot_text.splitlines()), 250)

            bundle_text = context_bundle.read_text(encoding="utf-8")
            self.assertIn("# SoT Bundle", bundle_text)
            self.assertTrue(
                bundle_text.startswith("# SoT Bundle\n")
                or "\n# SoT Bundle\n" in bundle_text
            )
            self.assertIn("# SRC: docs/prd/killer-7.md", bundle_text)
            self.assertIn("# SRC: hello.txt", bundle_text)
            self.assertIn("L1: hello", bundle_text)
            self.assertIn("# SRC: tail.txt", bundle_text)
            self.assertLessEqual(len(bundle_text.splitlines()), 1500)

            warn = warnings_txt.read_text(encoding="utf-8")
            self.assertIn("sot_truncated", warn)
            self.assertIn("context_bundle_total_truncated", warn)
            self.assertIn("context_bundle_file_truncated", warn)

    def test_creates_aspect_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            out_dir = Path(td) / ".ai-review" / "aspects"
            self.assertTrue((out_dir / "index.json").is_file())
            for a in [
                "correctness",
                "readability",
                "testing",
                "test-audit",
                "security",
                "performance",
                "refactoring",
            ]:
                self.assertTrue((out_dir / f"{a}.json").is_file())

    def test_creates_evidence_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            out_dir = Path(td) / ".ai-review"
            evidence = out_dir / "evidence.json"
            self.assertTrue(evidence.is_file())

            payload = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("schema_version"), 1)
            self.assertEqual(payload.get("kind"), "evidence_summary")
            self.assertIn("per_aspect", payload)

            aspects_dir = out_dir / "aspects"
            for a in [
                "correctness",
                "readability",
                "testing",
                "test-audit",
                "security",
                "performance",
                "refactoring",
            ]:
                p = aspects_dir / f"{a}.evidence.json"
                self.assertTrue(p.is_file())
                payload = json.loads(p.read_text(encoding="utf-8"))
                self.assertEqual(payload.get("schema_version"), 1)
                self.assertEqual(payload.get("kind"), "aspect_evidence")
                self.assertIn("review", payload)

                self.assertTrue((aspects_dir / f"{a}.policy.json").is_file())
                self.assertTrue((aspects_dir / f"{a}.raw.json").is_file())

            self.assertTrue((aspects_dir / "index.evidence.json").is_file())
            self.assertTrue((aspects_dir / "index.policy.json").is_file())

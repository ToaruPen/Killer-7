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
    sys.stdout.write("diff --git a/hello.txt b/hello.txt\\n")
    sys.stdout.write("new file mode 100644\\n")
    sys.stdout.write("index 0000000..1111111\\n")
    sys.stdout.write("--- /dev/null\\n")
    sys.stdout.write("+++ b/hello.txt\\n")
    sys.stdout.write("@@ -0,0 +1 @@\\n")
    sys.stdout.write("+hello\\n")
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


def run_cli(
    args: list[str],
    cwd: str,
    *,
    gh_bin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    if gh_bin is not None:
        env["KILLER7_GH_BIN"] = gh_bin
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

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
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

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
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
            self.assertLessEqual(len(bundle_text.splitlines()), 1500)

            warn = warnings_txt.read_text(encoding="utf-8")
            self.assertIn("sot_truncated", warn)

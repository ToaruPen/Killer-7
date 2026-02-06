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

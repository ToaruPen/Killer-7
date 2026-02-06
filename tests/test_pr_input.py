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
    sys.stdout.write("diff --git a/hello.txt b/hello.txt\\n")
    sys.stdout.write("new file mode 100644\\n")
    sys.stdout.write("index 0000000..1111111\\n")
    sys.stdout.write("--- /dev/null\\n")
    sys.stdout.write("+++ b/hello.txt\\n")
    sys.stdout.write("@@ -0,0 +1 @@\\n")
    sys.stdout.write("+hello\\n")
    raise SystemExit(0)

if args[:2] == ["pr", "view"]:
    sys.stdout.write(json.dumps({"headRefOid": "0123456789abcdef"}))
    raise SystemExit(0)

if args[:1] == ["api"]:
    endpoint = args[-1]
    if endpoint.endswith("/pulls/123/files"):
        files = [
            {"filename": "hello.txt", "status": "added", "additions": 1, "deletions": 0},
            {"filename": "old.txt", "status": "removed", "additions": 0, "deletions": 10},
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


def _write_fake_gh_auth_blocked(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import sys

sys.stderr.write("You are not logged into any GitHub hosts. Run: gh auth login\\n")
raise SystemExit(1)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def run_cli(
    args: list[str], cwd: str, *, gh_bin: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
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


class TestPrInputArtifacts(unittest.TestCase):
    def test_review_writes_pr_input_artifacts(self) -> None:
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
            self.assertTrue((out_dir / "diff.patch").is_file())
            self.assertTrue((out_dir / "changed-files.tsv").is_file())
            self.assertTrue((out_dir / "meta.json").is_file())

            patch = (out_dir / "diff.patch").read_text(encoding="utf-8")
            self.assertIn("diff --git", patch)

            changed = (
                (out_dir / "changed-files.tsv").read_text(encoding="utf-8").splitlines()
            )
            self.assertGreaterEqual(len(changed), 2)
            self.assertEqual(
                changed[0], "path\tstatus\tprevious_path\tadditions\tdeletions"
            )
            self.assertIn("hello.txt\tadded\t\t1\t0", changed)
            self.assertIn("old.txt\tremoved\t\t0\t10", changed)
            self.assertIn("newname.txt\trenamed\toldname.txt\t0\t0", changed)

            meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["repo"], "owner/name")
            self.assertEqual(meta["pr"], 123)
            self.assertEqual(meta["head_sha"], "0123456789abcdef")

    def test_review_auth_blocked_exits_1_and_writes_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh_auth_blocked(fake_gh)

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
            )
            self.assertEqual(p.returncode, 1)

            run_json = Path(td) / ".ai-review" / "run.json"
            self.assertTrue(run_json.is_file())
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["exit_code"], 1)
            self.assertEqual(payload["status"], "blocked")


if __name__ == "__main__":
    raise SystemExit(unittest.main())

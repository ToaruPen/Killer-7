from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_fake_gh(path: Path) -> None:
    """Write a tiny fake `gh` binary for tests."""

    path.write_text(
        """#!/usr/bin/env python3
import json
import os
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
    seq = os.environ.get("KILLER7_TEST_HEAD_SEQ", "")
    if seq:
        values = [x.strip() for x in seq.split(",") if x.strip()]
        if values:
            state_file = os.environ.get(
                "KILLER7_TEST_HEAD_SEQ_STATE", ".fake-gh-head-seq-count"
            )
            try:
                with open(state_file, "r", encoding="utf-8") as fh:
                    count = int((fh.read() or "0").strip() or "0")
            except FileNotFoundError:
                count = 0
            idx = count if count < len(values) else len(values) - 1
            with open(state_file, "w", encoding="utf-8") as fh:
                fh.write(str(count + 1))
            sys.stdout.write(json.dumps({"headRefOid": values[idx]}))
            raise SystemExit(0)

    sys.stdout.write(json.dumps({"headRefOid": "0123456789abcdef"}))
    raise SystemExit(0)

if args[:1] == ["api"]:
    endpoint = args[-1]
    if "/compare/" in endpoint:
        sys.stdout.write("diff --git a/inc.txt b/inc.txt\\n")
        sys.stdout.write("index 0000000..1111111 100644\\n")
        sys.stdout.write("--- a/inc.txt\\n")
        sys.stdout.write("+++ b/inc.txt\\n")
        sys.stdout.write("@@ -0,0 +1 @@\\n")
        sys.stdout.write("+incremental-line\\n")
        raise SystemExit(0)

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

    # SoT collection (Issue #4) calls commit/tree endpoints.
    if "/commits/" in endpoint:
        sys.stdout.write(json.dumps({"commit": {"tree": {"sha": "TREE123"}}}))
        raise SystemExit(0)

    if "/git/trees/" in endpoint:
        sys.stdout.write(json.dumps({"truncated": False, "tree": []}))
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


def _write_fake_opencode(path: Path) -> None:
    """Write a tiny fake `opencode` binary for tests."""

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
    gh_bin: str,
    opencode_bin: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["KILLER7_GH_BIN"] = gh_bin
    if opencode_bin is not None:
        env["KILLER7_OPENCODE_BIN"] = opencode_bin
    if extra_env:
        env.update(extra_env)
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
    def test_fetch_pr_input_uses_compare_diff_when_base_head_is_given(self) -> None:
        from killer_7.github.pr_input import fetch_pr_input

        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)

            with patch.dict(os.environ, {"KILLER7_GH_BIN": str(fake_gh)}):
                pr_input = fetch_pr_input(
                    repo="owner/name",
                    pr=123,
                    base_head_sha="aaaaaaaaaaaaaaaa",
                )

            self.assertEqual(pr_input.diff_mode, "incremental")
            self.assertEqual(pr_input.base_head_sha, "aaaaaaaaaaaaaaaa")
            self.assertIn("incremental-line", pr_input.diff_patch)

    def test_fetch_pr_input_falls_back_to_full_when_base_equals_head(self) -> None:
        from killer_7.github.pr_input import fetch_pr_input

        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)

            with patch.dict(os.environ, {"KILLER7_GH_BIN": str(fake_gh)}):
                pr_input = fetch_pr_input(
                    repo="owner/name",
                    pr=123,
                    base_head_sha="0123456789abcdef",
                )

            self.assertEqual(pr_input.diff_mode, "full")
            self.assertEqual(pr_input.base_head_sha, "")
            self.assertNotIn("incremental-line", pr_input.diff_patch)

    def test_review_writes_pr_input_artifacts(self) -> None:
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

    def test_review_exits_2_when_pr_head_changes_during_input_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                extra_env={
                    "KILLER7_TEST_HEAD_SEQ": "0123456789abcdef,fedcba9876543210",
                    "KILLER7_TEST_HEAD_SEQ_STATE": ".head-seq-state",
                },
            )
            self.assertEqual(p.returncode, 2)

            run_json = Path(td) / ".ai-review" / "run.json"
            self.assertTrue(run_json.is_file())
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "exec_failure")
            self.assertIn(
                "PR head changed during input fetch",
                payload.get("error", {}).get("message", ""),
            )

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

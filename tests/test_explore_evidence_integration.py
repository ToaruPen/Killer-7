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
    path.write_text(
        """#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]

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
        sys.stdout.write(json.dumps([]))
        raise SystemExit(0)
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


def _write_fake_opencode_explore_read(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import re
import sys

_ = sys.stdin.read()

payload = {
  "schema_version": 3,
  "scope_id": "owner/name#pr-123@0123456789ab",
  "status": "Blocked",
  "findings": [
    {
      "priority": "P0",
      "title": "x.txt check",
      "body": "test",
      "sources": ["x.txt#L1-L1"],
      "code_location": {"repo_relative_path": "x.txt", "line_range": {"start": 1, "end": 1}}
    }
  ],
  "questions": [],
  "overall_explanation": "ok",
}

events = [
  {
    "type": "tool_use",
    "timestamp": 2,
    "sessionID": "ses_x",
    "part": {
      "type": "tool",
      "callID": "call_1",
      "tool": "read",
      "state": {
        "status": "completed",
        "input": {"filePath": "x.txt", "offset": 1, "limit": 1},
        "output": "",
        "title": "",
        "metadata": {},
        "time": {"start": 1, "end": 2},
        "attachments": []
      }
    }
  },
  {"type": "text", "part": {"text": json.dumps(payload)}},
]

for e in events:
  sys.stdout.write(json.dumps(e) + "\\n")

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
    opencode_bin: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["KILLER7_GH_BIN"] = gh_bin
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


class TestExploreEvidenceIntegration(unittest.TestCase):
    def test_explore_mode_makes_tool_sources_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "x.txt").write_text("hello\\n", encoding="utf-8")

            subprocess.run(
                ["git", "init", "-q"],
                cwd=td,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            subprocess.run(
                ["git", "add", "x.txt"],
                cwd=td,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)

            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_explore_read(fake_opencode)

            p = run_cli(
                [
                    "review",
                    "--repo",
                    "owner/name",
                    "--pr",
                    "123",
                    "--aspect",
                    "correctness",
                    "--explore",
                ],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 1, msg=(p.stdout + "\n" + p.stderr))

            out_dir = Path(td) / ".ai-review"
            self.assertTrue((out_dir / "tool-bundle.txt").is_file())

            evidence_path = out_dir / "aspects" / "correctness.evidence.json"
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            stats = payload.get("stats")
            self.assertIsInstance(stats, dict)
            if isinstance(stats, dict):
                self.assertEqual(stats.get("verified_true_count"), 1)
                self.assertEqual(stats.get("downgraded_count"), 0)


if __name__ == "__main__":
    raise SystemExit(unittest.main())

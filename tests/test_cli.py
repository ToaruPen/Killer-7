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
STATE_PATH = "fake-gh-state.json"


def read_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"comments": [], "next_id": 1}


def write_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh)


def arg_value(flag: str) -> str:
    i = 0
    while i < len(args):
        if args[i] == flag and i + 1 < len(args):
            return args[i + 1]
        i += 1
    return ""


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
    state = read_state()
    head = "0123456789abcdef"
    seq = state.get("head_ref_oid_sequence")
    if isinstance(seq, list) and seq:
        head = str(seq[0])
        state["head_ref_oid_sequence"] = seq[1:]
        write_state(state)
    else:
        current = state.get("head_ref_oid")
        if isinstance(current, str) and current:
            head = current
    sys.stdout.write(json.dumps({"headRefOid": head}))
    raise SystemExit(0)


if args[:1] == ["api"]:
    if args[1:] == ["user"]:
        state = read_state()
        viewer = state.get("viewer_login")
        login = viewer if isinstance(viewer, str) and viewer else "owner"
        sys.stdout.write(json.dumps({"login": login}))
        raise SystemExit(0)

    # gh api [flags...] <endpoint>
    endpoint = ""
    for token in args[1:]:
        if token.startswith("repos/"):
            endpoint = token
            break
    if not endpoint:
        sys.stderr.write("fake gh: missing endpoint\\n")
        raise SystemExit(2)

    if endpoint.endswith("/issues/123/comments"):
        if "-X" in args and arg_value("-X") == "POST":
            body = arg_value("-f").removeprefix("body=")
            state = read_state()
            viewer = state.get("viewer_login")
            login = viewer if isinstance(viewer, str) and viewer else "owner"
            comment = {"id": state["next_id"], "body": body, "user": {"login": login}}
            state["next_id"] += 1
            state["comments"].append(comment)

            # Test hook: simulate a concurrent runner creating another marker comment
            # right after this create call.
            if state.get("race_duplicate_on_post"):
                state["comments"].append(
                    {
                        "id": state["next_id"],
                        "body": state.get(
                            "race_marker_body", "<!-- killer-7:summary:v1 -->\\nrace"
                        ),
                        "user": {"login": login},
                    }
                )
                state["next_id"] += 1
                state["race_duplicate_on_post"] = False

            write_state(state)
            sys.stdout.write(json.dumps(comment))
            raise SystemExit(0)

        state = read_state()
        comments = state["comments"]
        if has("--slurp"):
            sys.stdout.write(json.dumps([comments]))
        else:
            # Simulate default API pagination: without --paginate only first page is returned.
            sys.stdout.write(json.dumps(comments[:1]))
        raise SystemExit(0)

    if endpoint.startswith("repos/owner/name/issues/comments/"):
        method = arg_value("-X")
        if "-X" not in args or method not in ("PATCH", "DELETE"):
            sys.stderr.write("Method Not Allowed\\n")
            raise SystemExit(1)
        comment_id = int(endpoint.rsplit("/", 1)[-1])
        state = read_state()

        # Test hook: force one-shot PATCH 404 for selected ids
        if method == "PATCH":
            missing_ids = state.get("patch_not_found_ids", [])
            if isinstance(missing_ids, list) and comment_id in missing_ids:
                state["patch_not_found_ids"] = [
                    x for x in missing_ids if int(x) != comment_id
                ]
                state["comments"] = [
                    c for c in state["comments"] if int(c.get("id", 0)) != comment_id
                ]
                write_state(state)
                sys.stderr.write("Not Found\\n")
                raise SystemExit(1)

        for i, comment in enumerate(state["comments"]):
            if int(comment.get("id", 0)) == comment_id:
                if method == "PATCH":
                    body = arg_value("-f").removeprefix("body=")
                    comment["body"] = body
                    write_state(state)
                    sys.stdout.write(json.dumps(comment))
                else:
                    del state["comments"][i]
                    write_state(state)
                    sys.stdout.write("{}")
                raise SystemExit(0)
        sys.stderr.write("Not Found\\n")
        raise SystemExit(1)

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


def _write_fake_opencode_blocked(path: Path) -> None:
    """Fake opencode that returns a blocking P0 for one aspect."""

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
m2 = re.search("^Aspect:\\s*(.+)\\s*$", prompt, flags=re.M)
aspect = m2.group(1).strip() if m2 else ""

payload = {
  "schema_version": 3,
  "scope_id": scope_id,
  "status": "Approved",
  "findings": [],
  "questions": [],
  "overall_explanation": "ok",
}

if aspect == "correctness":
  payload["status"] = "Blocked"
  payload["findings"] = [
    {
      "title": "Blocking issue",
      "body": "Evidence-backed blocking issue.",
      "priority": "P0",
      "sources": ["hello.txt#L1-L1"],
      "code_location": {"repo_relative_path": "hello.txt", "line_range": {"start": 1, "end": 1}},
    }
  ]
  payload["overall_explanation"] = "Blocking issue."

event = {"type": "text", "part": {"text": json.dumps(payload)}}
sys.stdout.write(json.dumps(event) + "\\n")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_blocked_with_question(path: Path) -> None:
    """Fake opencode that returns a P0 finding and a question."""

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
m2 = re.search("^Aspect:\\s*(.+)\\s*$", prompt, flags=re.M)
aspect = m2.group(1).strip() if m2 else ""

payload = {
  "schema_version": 3,
  "scope_id": scope_id,
  "status": "Approved",
  "findings": [],
  "questions": [],
  "overall_explanation": "ok",
}

if aspect == "correctness":
  payload["status"] = "Blocked"
  payload["findings"] = [
    {
      "title": "Blocking issue",
      "body": "Evidence-backed blocking issue.",
      "priority": "P0",
      "sources": ["hello.txt#L1-L1"],
      "code_location": {"repo_relative_path": "hello.txt", "line_range": {"start": 1, "end": 1}},
    }
  ]
  payload["questions"] = ["Can you clarify this?"]
  payload["overall_explanation"] = "Blocking issue and a question."

event = {"type": "text", "part": {"text": json.dumps(payload)}}
sys.stdout.write(json.dumps(event) + "\\n")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_exec_failure(path: Path) -> None:
    """Fake opencode that always fails."""

    path.write_text(
        """#!/usr/bin/env python3
import sys

sys.stderr.write("fake opencode: exec failure\\n")
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

    def test_creates_review_summary_artifacts(self) -> None:
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
            summary_json = out_dir / "review-summary.json"
            summary_md = out_dir / "review-summary.md"
            self.assertTrue(summary_json.is_file())
            self.assertTrue(summary_md.is_file())

            payload = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("schema_version"), 3)
            self.assertEqual(payload.get("status"), "Approved")

    def test_blocked_summary_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_blocked(fake_opencode)

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 1, msg=(p.stdout + "\n" + p.stderr))

            out_dir = Path(td) / ".ai-review"
            summary_json = out_dir / "review-summary.json"
            summary_md = out_dir / "review-summary.md"
            self.assertTrue(summary_json.is_file())
            self.assertTrue(summary_md.is_file())

            payload = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("status"), "Blocked")

    def test_blocked_with_question_exits_1(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_blocked_with_question(fake_opencode)

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 1, msg=(p.stdout + "\n" + p.stderr))

            out_dir = Path(td) / ".ai-review"
            summary_json = out_dir / "review-summary.json"
            self.assertTrue(summary_json.is_file())
            payload = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("status"), "Blocked")

    def test_missing_opencode_still_writes_blocked_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)

            # Force a deterministic missing binary case.
            missing_opencode = Path(td) / "opencode-missing"

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(missing_opencode),
            )
            self.assertEqual(p.returncode, 1, msg=(p.stdout + "\n" + p.stderr))

            out_dir = Path(td) / ".ai-review"
            summary_json = out_dir / "review-summary.json"
            self.assertTrue(summary_json.is_file())

            payload = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("status"), "Blocked")
            explanation = (payload.get("overall_explanation") or "").lower()
            self.assertTrue(
                ("blocked" in explanation) or ("opencode" in explanation),
                msg=f"unexpected overall_explanation: {payload.get('overall_explanation')!r}",
            )

    def test_exec_failure_clears_stale_review_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)

            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            p1 = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p1.returncode, 0, msg=(p1.stdout + "\n" + p1.stderr))

            out_dir = Path(td) / ".ai-review"
            summary_json = out_dir / "review-summary.json"
            summary_md = out_dir / "review-summary.md"
            self.assertTrue(summary_json.is_file())
            self.assertTrue(summary_md.is_file())

            _write_fake_opencode_exec_failure(fake_opencode)
            p2 = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p2.returncode, 2, msg=(p2.stdout + "\n" + p2.stderr))
            self.assertFalse(summary_json.exists())
            self.assertFalse(summary_md.exists())

    def test_post_summary_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            p1 = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123", "--post"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p1.returncode, 0, msg=(p1.stdout + "\n" + p1.stderr))

            p2 = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123", "--post"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p2.returncode, 0, msg=(p2.stdout + "\n" + p2.stderr))

            state_path = Path(td) / "fake-gh-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 1)
            body = comments[0].get("body", "")
            self.assertIn("<!-- killer-7:summary:v1 -->", body)
            self.assertIn("## Counts", body)
            self.assertIn("head_sha", body)

    def test_post_summary_updates_existing_marker_beyond_first_page(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            state_path = Path(td) / "fake-gh-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "comments": [
                            {"id": 1, "body": "older comment"},
                            {
                                "id": 2,
                                "body": "<!-- killer-7:summary:v1 -->\nold",
                                "user": {"login": "owner"},
                            },
                        ],
                        "next_id": 3,
                    }
                ),
                encoding="utf-8",
            )

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123", "--post"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 2)
            self.assertIn("<!-- killer-7:summary:v1 -->", comments[1].get("body", ""))
            self.assertIn("## Counts", comments[1].get("body", ""))

    def test_post_summary_updates_newest_marker_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            state_path = Path(td) / "fake-gh-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "comments": [
                            {
                                "id": 1,
                                "body": "<!-- killer-7:summary:v1 -->\nold-1",
                                "user": {"login": "owner"},
                            },
                            {
                                "id": 2,
                                "body": "<!-- killer-7:summary:v1 -->\nold-2",
                                "user": {"login": "owner"},
                            },
                        ],
                        "next_id": 3,
                    }
                ),
                encoding="utf-8",
            )

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123", "--post"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 1)
            self.assertEqual(comments[0].get("id"), 2)
            self.assertIn("## Counts", comments[0].get("body", ""))

    def test_post_summary_reconciles_create_race_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            state_path = Path(td) / "fake-gh-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "comments": [],
                        "next_id": 1,
                        "race_duplicate_on_post": True,
                    }
                ),
                encoding="utf-8",
            )

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123", "--post"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 1)
            self.assertIn("<!-- killer-7:summary:v1 -->", comments[0].get("body", ""))
            self.assertIn("## Counts", comments[0].get("body", ""))

    def test_post_summary_skips_when_head_moved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            state_path = Path(td) / "fake-gh-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "comments": [],
                        "next_id": 1,
                        "head_ref_oid_sequence": [
                            "0123456789abcdef",
                            "fedcba9876543210",
                        ],
                    }
                ),
                encoding="utf-8",
            )

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123", "--post"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 0)

            run_json = Path(td) / ".ai-review" / "run.json"
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            summary_comment = (
                payload.get("result", {})
                .get("artifacts", {})
                .get("summary_comment", {})
            )
            self.assertEqual(summary_comment.get("mode"), "skipped_stale_head")

    def test_post_summary_recovers_when_target_marker_deleted_mid_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            state_path = Path(td) / "fake-gh-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "comments": [
                            {
                                "id": 1,
                                "body": "<!-- killer-7:summary:v1 -->\nold-1",
                                "user": {"login": "owner"},
                            },
                            {
                                "id": 2,
                                "body": "<!-- killer-7:summary:v1 -->\nold-2",
                                "user": {"login": "owner"},
                            },
                        ],
                        "next_id": 3,
                        "patch_not_found_ids": [2],
                    }
                ),
                encoding="utf-8",
            )

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123", "--post"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 1)
            self.assertEqual(comments[0].get("id"), 1)
            self.assertIn("## Counts", comments[0].get("body", ""))

    def test_post_summary_ignores_marker_from_other_author(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            state_path = Path(td) / "fake-gh-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "comments": [
                            {
                                "id": 1,
                                "body": "<!-- killer-7:summary:v1 -->\nforeign",
                                "user": {"login": "someone-else"},
                            }
                        ],
                        "next_id": 2,
                        "viewer_login": "owner",
                    }
                ),
                encoding="utf-8",
            )

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123", "--post"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 2)
            self.assertEqual(comments[0].get("id"), 1)
            self.assertIn("foreign", comments[0].get("body", ""))
            self.assertEqual(comments[1].get("id"), 2)
            self.assertEqual(comments[1].get("user", {}).get("login"), "owner")
            self.assertIn("## Counts", comments[1].get("body", ""))

    def test_post_summary_even_when_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_blocked(fake_opencode)

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123", "--post"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 1, msg=(p.stdout + "\n" + p.stderr))

            state_path = Path(td) / "fake-gh-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 1)

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


def field_value(prefix: str) -> str:
    i = 0
    while i < len(args) - 1:
        if args[i] in ("-f", "-F") and args[i + 1].startswith(prefix):
            return args[i + 1][len(prefix) :]
        i += 1
    return ""


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
            state = read_state()
            post_error = state.get("post_comment_error_message")
            if isinstance(post_error, str) and post_error:
                sys.stderr.write(post_error + "\\n")
                raise SystemExit(1)

            body = arg_value("-f").removeprefix("body=")
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
        list_calls = int(state.get("list_calls", 0)) + 1
        state["list_calls"] = list_calls

        delete_call = state.get("delete_on_list_call")
        delete_id = state.get("delete_on_list_comment_id")
        if isinstance(delete_call, int) and list_calls == delete_call and isinstance(
            delete_id, int
        ):
            state["comments"] = [
                c for c in state["comments"] if int(c.get("id", 0)) != delete_id
            ]

        add_call = state.get("add_marker_on_list_call")
        if isinstance(add_call, int) and list_calls == add_call:
            marker_body_obj = state.get("add_marker_body")
            marker_body = (
                marker_body_obj
                if isinstance(marker_body_obj, str) and marker_body_obj
                else "<!-- killer-7:summary:v1 -->\\nrace-added"
            )
            author_obj = state.get("add_marker_author")
            author = author_obj if isinstance(author_obj, str) and author_obj else "owner"
            state["comments"].append(
                {
                    "id": state["next_id"],
                    "body": marker_body,
                    "user": {"login": author},
                }
            )
            state["next_id"] += 1

        write_state(state)
        comments = state["comments"]
        if has("--slurp"):
            sys.stdout.write(json.dumps([comments]))
        else:
            # Simulate default API pagination: without --paginate only first page is returned.
            sys.stdout.write(json.dumps(comments[:1]))
        raise SystemExit(0)

    if endpoint.endswith("/pulls/123/comments"):
        state = read_state()

        if "-X" in args and arg_value("-X") == "POST":
            body = field_value("body=")
            path = field_value("path=")
            commit_id = field_value("commit_id=")
            position_raw = field_value("position=")
            try:
                position = int(position_raw)
            except ValueError:
                position = -1

            login_obj = state.get("viewer_login")
            login = login_obj if isinstance(login_obj, str) and login_obj else "owner"

            next_review_id = int(state.get("next_review_id", 1))
            comment = {
                "id": next_review_id,
                "body": body,
                "path": path,
                "position": position,
                "commit_id": commit_id,
                "user": {"login": login},
            }
            review_comments = state.get("review_comments")
            if not isinstance(review_comments, list):
                review_comments = []
            review_comments.append(comment)
            state["review_comments"] = review_comments
            state["next_review_id"] = next_review_id + 1
            write_state(state)
            sys.stdout.write(json.dumps(comment))
            raise SystemExit(0)

        review_comments = state.get("review_comments")
        if not isinstance(review_comments, list):
            review_comments = []
        write_state(state)
        if has("--slurp"):
            sys.stdout.write(json.dumps([review_comments]))
        else:
            sys.stdout.write(json.dumps(review_comments))
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

        for comment in state["comments"]:
            if int(comment.get("id", 0)) == comment_id:
                if method == "PATCH":
                    body = arg_value("-f").removeprefix("body=")
                    comment["body"] = body
                    write_state(state)
                    sys.stdout.write(json.dumps(comment))
                else:
                    linked_delete_id = state.get("delete_other_target_comment_id")
                    linked_delete_trigger = state.get("delete_other_on_delete_comment_id")
                    ids_to_delete = {comment_id}
                    if (
                        isinstance(linked_delete_trigger, int)
                        and isinstance(linked_delete_id, int)
                        and linked_delete_trigger == comment_id
                    ):
                        ids_to_delete.add(linked_delete_id)
                        state.pop("delete_other_on_delete_comment_id", None)
                        state.pop("delete_other_target_comment_id", None)

                    state["comments"] = [
                        c
                        for c in state["comments"]
                        if int(c.get("id", 0)) not in ids_to_delete
                    ]
                    write_state(state)
                    sys.stdout.write("{}")
                raise SystemExit(0)
        sys.stderr.write("Not Found\\n")
        raise SystemExit(1)

    if endpoint.startswith("repos/owner/name/pulls/comments/"):
        method = arg_value("-X")
        if "-X" not in args or method != "DELETE":
            sys.stderr.write("Method Not Allowed\\n")
            raise SystemExit(1)

        comment_id = int(endpoint.rsplit("/", 1)[-1])
        state = read_state()
        review_comments = state.get("review_comments")
        if not isinstance(review_comments, list):
            review_comments = []
        state["review_comments"] = [
            c for c in review_comments if int(c.get("id", 0)) != comment_id
        ]
        write_state(state)
        sys.stdout.write("{}")
        raise SystemExit(0)

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
m = re.search(r"^Scope ID:\\s*(.+)\\s*$", prompt, flags=re.M)
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


def _write_fake_opencode_p2_tool_source(path: Path) -> None:
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
m = re.search(r"^Scope ID:\\s*(.+)\\s*$", prompt, flags=re.M)
scope_id = m.group(1).strip() if m else "scope-unknown"
m2 = re.search(r"^Aspect:\\s*(.+)\\s*$", prompt, flags=re.M)
aspect = m2.group(1).strip() if m2 else ""

payload = {
  "schema_version": 3,
  "scope_id": scope_id,
  "status": "Approved",
  "findings": [],
  "questions": [],
  "overall_explanation": "ok",
}

if aspect == "readability":
  payload["status"] = "Approved with nits"
  payload["findings"] = [
    {
      "title": "Tool-sourced nit",
      "body": "This finding cites a path that is only present in a tool bundle.",
      "priority": "P2",
      "sources": ["tool-only.txt#L1-L1"],
      "code_location": {"repo_relative_path": "tool-only.txt", "line_range": {"start": 1, "end": 1}},
    }
  ]
  payload["overall_explanation"] = "One P2 nit sourced from tool bundle."

event = {"type": "text", "part": {"text": json.dumps(payload)}}
sys.stdout.write(json.dumps(event) + "\\n")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_p2_tool_source_writes_tool_bundle(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import re
import sys

args = sys.argv[1:]

if args[:1] != ["run"]:
    sys.stderr.write("fake opencode: unsupported args: " + " ".join(args) + "\\n")
    raise SystemExit(2)

prompt = sys.stdin.read()
m = re.search(r"^Scope ID:\\s*(.+)\\s*$", prompt, flags=re.M)
scope_id = m.group(1).strip() if m else "scope-unknown"
m2 = re.search(r"^Aspect:\\s*(.+)\\s*$", prompt, flags=re.M)
aspect = m2.group(1).strip() if m2 else ""

payload = {
  "schema_version": 3,
  "scope_id": scope_id,
  "status": "Approved",
  "findings": [],
  "questions": [],
  "overall_explanation": "ok",
}

if aspect == "readability":
  tool_dir = os.path.join(os.getcwd(), ".ai-review", "tool-bundle")
  os.makedirs(tool_dir, exist_ok=True)
  manifest = {
    "schema_version": 1,
    "head_sha": "0123456789abcdef",
    "files": ["bundle.txt"],
  }
  with open(os.path.join(tool_dir, "manifest.json"), "w", encoding="utf-8") as fh:
    fh.write(json.dumps(manifest) + "\\n")
  with open(os.path.join(tool_dir, "bundle.txt"), "w", encoding="utf-8") as fh:
    fh.write("# SRC: tool-only.txt\\n")
    fh.write("L1: hello\\n")

  payload["status"] = "Approved with nits"
  payload["findings"] = [
    {
      "title": "Tool-sourced nit",
      "body": "This finding cites a path that is only present in a tool bundle.",
      "priority": "P2",
      "sources": ["tool-only.txt#L1-L1"],
      "code_location": {"repo_relative_path": "tool-only.txt", "line_range": {"start": 1, "end": 1}},
    }
  ]
  payload["overall_explanation"] = "One P2 nit sourced from tool bundle."

event = {"type": "text", "part": {"text": json.dumps(payload)}}
sys.stdout.write(json.dumps(event) + "\\n")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_p2_tool_source_dot_slash(path: Path) -> None:
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
m = re.search(r"^Scope ID:\\s*(.+)\\s*$", prompt, flags=re.M)
scope_id = m.group(1).strip() if m else "scope-unknown"
m2 = re.search(r"^Aspect:\\s*(.+)\\s*$", prompt, flags=re.M)
aspect = m2.group(1).strip() if m2 else ""

payload = {
  "schema_version": 3,
  "scope_id": scope_id,
  "status": "Approved",
  "findings": [],
  "questions": [],
  "overall_explanation": "ok",
}

if aspect == "readability":
  payload["status"] = "Approved with nits"
  payload["findings"] = [
    {
      "title": "Tool-sourced nit",
      "body": "This finding cites a path that is only present in a tool bundle.",
      "priority": "P2",
      "sources": ["./tool-only.txt#L1-L1"],
      "code_location": {"repo_relative_path": "./tool-only.txt", "line_range": {"start": 1, "end": 1}},
    }
  ]
  payload["overall_explanation"] = "One P2 nit sourced from tool bundle."

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
m = re.search(r"^Scope ID:\\s*(.+)\\s*$", prompt, flags=re.M)
scope_id = m.group(1).strip() if m else "scope-unknown"
m2 = re.search(r"^Aspect:\\s*(.+)\\s*$", prompt, flags=re.M)
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
m = re.search(r"^Scope ID:\\s*(.+)\\s*$", prompt, flags=re.M)
scope_id = m.group(1).strip() if m else "scope-unknown"
m2 = re.search(r"^Aspect:\\s*(.+)\\s*$", prompt, flags=re.M)
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

    def test_review_help_mentions_aspect_and_preset_flags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = run_cli(["review", "--help"], cwd=td)
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))
            out = p.stdout + "\n" + p.stderr
            self.assertIn("--aspect", out)
            self.assertIn("--preset", out)
            self.assertIn("--hybrid-aspect", out)
            self.assertIn("--hybrid-allowlist", out)

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

    def test_aspect_opt_in_runs_only_selected_aspects(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            p = run_cli(
                [
                    "review",
                    "--repo",
                    "owner/name",
                    "--pr",
                    "123",
                    "--aspect",
                    "correctness",
                    "--aspect",
                    "security",
                ],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            aspects_dir = Path(td) / ".ai-review" / "aspects"
            self.assertTrue((aspects_dir / "index.json").is_file())
            self.assertTrue((aspects_dir / "correctness.json").is_file())
            self.assertTrue((aspects_dir / "security.json").is_file())
            self.assertFalse((aspects_dir / "readability.json").exists())

            idx = json.loads((aspects_dir / "index.json").read_text(encoding="utf-8"))
            names = [x.get("aspect") for x in idx.get("aspects", [])]
            self.assertEqual(names, ["correctness", "security"])

            run_json = Path(td) / ".ai-review" / "run.json"
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(
                payload.get("result", {}).get("selected_aspects"),
                ["correctness", "security"],
            )

    def test_preset_minimal_runs_expected_aspects(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            p = run_cli(
                [
                    "review",
                    "--repo",
                    "owner/name",
                    "--pr",
                    "123",
                    "--preset",
                    "minimal",
                ],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            aspects_dir = Path(td) / ".ai-review" / "aspects"
            self.assertTrue((aspects_dir / "correctness.json").is_file())
            self.assertTrue((aspects_dir / "security.json").is_file())
            self.assertFalse((aspects_dir / "readability.json").exists())

            run_json = Path(td) / ".ai-review" / "run.json"
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(
                payload.get("result", {}).get("selected_aspects"),
                ["correctness", "security"],
            )

    def test_duplicate_aspect_is_invalid_args_and_does_not_delete_existing_summaries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / ".ai-review"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "review-summary.json").write_text("{}\n", encoding="utf-8")
            (out_dir / "review-summary.md").write_text("stale\n", encoding="utf-8")

            p = run_cli(
                [
                    "review",
                    "--repo",
                    "owner/name",
                    "--pr",
                    "123",
                    "--aspect",
                    "correctness",
                    "--aspect",
                    "Correctness",
                ],
                cwd=td,
            )
            self.assertEqual(p.returncode, 2, msg=(p.stdout + "\n" + p.stderr))
            self.assertIn("Duplicate aspect", p.stderr)

            self.assertTrue((out_dir / "review-summary.json").is_file())
            self.assertTrue((out_dir / "review-summary.md").is_file())

            run_json = out_dir / "run.json"
            self.assertTrue(run_json.is_file())
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "invalid_args")
            self.assertIn(
                "Duplicate aspect", payload.get("error", {}).get("message", "")
            )

    def test_unknown_preset_is_invalid_args_and_does_not_delete_existing_summaries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / ".ai-review"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "review-summary.json").write_text("{}\n", encoding="utf-8")
            (out_dir / "review-summary.md").write_text("stale\n", encoding="utf-8")

            p = run_cli(
                [
                    "review",
                    "--repo",
                    "owner/name",
                    "--pr",
                    "123",
                    "--preset",
                    "nope",
                ],
                cwd=td,
            )
            self.assertEqual(p.returncode, 2, msg=(p.stdout + "\n" + p.stderr))
            self.assertIn("Unknown preset", p.stderr)

            self.assertTrue((out_dir / "review-summary.json").is_file())
            self.assertTrue((out_dir / "review-summary.md").is_file())

            run_json = out_dir / "run.json"
            self.assertTrue(run_json.is_file())
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "invalid_args")

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

    def test_tool_bundle_extends_evidence_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_p2_tool_source(fake_opencode)

            tool_dir = Path(td) / ".ai-review" / "tool-bundle"
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "head_sha": "0123456789abcdef",
                        "files": ["bundle.txt"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (tool_dir / "bundle.txt").write_text(
                "".join(
                    [
                        "# SRC: ./tool-only.txt\n",
                        "L1: hello\n",
                    ]
                ),
                encoding="utf-8",
            )

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            evidence_path = (
                Path(td) / ".ai-review" / "aspects" / "readability.evidence.json"
            )
            self.assertTrue(evidence_path.is_file())
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            review = evidence.get("review")
            self.assertTrue(isinstance(review, dict))
            findings = review.get("findings")
            self.assertTrue(isinstance(findings, list))
            self.assertTrue(findings, msg="expected at least one finding")
            f0 = findings[0]
            self.assertTrue(isinstance(f0, dict))
            self.assertEqual(f0.get("priority"), "P2")
            self.assertEqual(f0.get("verified"), True)

    def test_tool_bundle_generated_during_run_extends_evidence_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_p2_tool_source_writes_tool_bundle(fake_opencode)

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            evidence_path = (
                Path(td) / ".ai-review" / "aspects" / "readability.evidence.json"
            )
            self.assertTrue(evidence_path.is_file())
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            review = evidence.get("review")
            self.assertTrue(isinstance(review, dict))
            findings = review.get("findings")
            self.assertTrue(isinstance(findings, list))
            self.assertTrue(findings, msg="expected at least one finding")
            f0 = findings[0]
            self.assertTrue(isinstance(f0, dict))
            self.assertEqual(f0.get("priority"), "P2")
            self.assertEqual(f0.get("verified"), True)

            run_json = Path(td) / ".ai-review" / "run.json"
            self.assertTrue(run_json.is_file())
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            result = payload.get("result")
            self.assertTrue(isinstance(result, dict))
            artifacts = result.get("artifacts")
            self.assertTrue(isinstance(artifacts, dict))
            files = artifacts.get("tool_bundle_files")
            self.assertTrue(isinstance(files, list))
            self.assertIn(".ai-review/tool-bundle/bundle.txt", files)

    def test_tool_bundle_symlink_is_skipped(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("os.symlink not available")

        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_p2_tool_source(fake_opencode)

            tool_dir = Path(td) / ".ai-review" / "tool-bundle"
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "head_sha": "0123456789abcdef",
                        "files": ["bundle.txt", "link.txt"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (tool_dir / "bundle.txt").write_text(
                "".join(
                    [
                        "# SRC: tool-only.txt\n",
                        "L1: hello\n",
                    ]
                ),
                encoding="utf-8",
            )

            outside = Path(td) / "outside.txt"
            outside.write_text("secret\n", encoding="utf-8")
            link = tool_dir / "link.txt"
            try:
                os.symlink(str(outside), str(link))
            except OSError as exc:
                self.skipTest(f"symlink not supported: {exc}")

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            evidence_path = (
                Path(td) / ".ai-review" / "aspects" / "readability.evidence.json"
            )
            self.assertTrue(evidence_path.is_file())
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            review = evidence.get("review")
            self.assertTrue(isinstance(review, dict))
            findings = review.get("findings")
            self.assertTrue(isinstance(findings, list))
            self.assertTrue(findings)
            f0 = findings[0]
            self.assertTrue(isinstance(f0, dict))
            self.assertEqual(f0.get("priority"), "P2")
            self.assertEqual(f0.get("verified"), True)

            run_json = Path(td) / ".ai-review" / "run.json"
            self.assertTrue(run_json.is_file())
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            result = payload.get("result")
            self.assertTrue(isinstance(result, dict))
            artifacts = result.get("artifacts")
            self.assertTrue(isinstance(artifacts, dict))
            files = artifacts.get("tool_bundle_files")
            self.assertTrue(isinstance(files, list))
            self.assertIn(".ai-review/tool-bundle/bundle.txt", files)
            self.assertNotIn(".ai-review/tool-bundle/link.txt", files)

            warnings_txt = Path(td) / ".ai-review" / "warnings.txt"
            self.assertTrue(warnings_txt.is_file())
            warn = warnings_txt.read_text(encoding="utf-8")
            self.assertIn("tool_bundle_file_skipped", warn)
            self.assertIn("kind=is_symlink", warn)
            self.assertIn("link.txt", warn)

    def test_tool_bundle_manifest_head_sha_requires_exact_match(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            tool_dir = Path(td) / ".ai-review" / "tool-bundle"
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "head_sha": "0123456",
                        "files": ["bundle.txt"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (tool_dir / "bundle.txt").write_text(
                "".join(
                    [
                        "# SRC: tool-only.txt\n",
                        "L1: hello\n",
                    ]
                ),
                encoding="utf-8",
            )

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            run_json = Path(td) / ".ai-review" / "run.json"
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            result = payload.get("result")
            self.assertTrue(isinstance(result, dict))
            artifacts = result.get("artifacts")
            self.assertTrue(isinstance(artifacts, dict))
            files = artifacts.get("tool_bundle_files")
            self.assertTrue(isinstance(files, list))
            self.assertEqual(files, [])

            warnings_txt = Path(td) / ".ai-review" / "warnings.txt"
            warn = warnings_txt.read_text(encoding="utf-8")
            self.assertIn("tool_bundle_manifest_skipped", warn)
            self.assertIn("kind=head_sha_mismatch", warn)

    def test_tool_bundle_extends_evidence_index_dot_slash_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_p2_tool_source_dot_slash(fake_opencode)

            tool_dir = Path(td) / ".ai-review" / "tool-bundle"
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "head_sha": "0123456789abcdef",
                        "files": ["bundle.txt"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (tool_dir / "bundle.txt").write_text(
                "".join(
                    [
                        "# SRC: tool-only.txt\n",
                        "L1: hello\n",
                    ]
                ),
                encoding="utf-8",
            )

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            evidence_path = (
                Path(td) / ".ai-review" / "aspects" / "readability.evidence.json"
            )
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            review = evidence.get("review")
            self.assertTrue(isinstance(review, dict))
            findings = review.get("findings")
            self.assertTrue(isinstance(findings, list))
            self.assertTrue(findings)
            f0 = findings[0]
            self.assertEqual(f0.get("priority"), "P2")
            self.assertEqual(f0.get("verified"), True)

    def test_run_json_records_tool_bundle_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_p2_tool_source(fake_opencode)

            tool_dir = Path(td) / ".ai-review" / "tool-bundle"
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "head_sha": "0123456789abcdef",
                        "files": ["bundle.txt"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (tool_dir / "bundle.txt").write_text(
                "".join(
                    [
                        "# SRC: tool-only.txt\n",
                        "L1: hello\n",
                    ]
                ),
                encoding="utf-8",
            )

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            run_json = Path(td) / ".ai-review" / "run.json"
            self.assertTrue(run_json.is_file())
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            result = payload.get("result")
            self.assertTrue(isinstance(result, dict))
            artifacts = result.get("artifacts")
            self.assertTrue(isinstance(artifacts, dict))
            files = artifacts.get("tool_bundle_files")
            self.assertTrue(isinstance(files, list))
            self.assertIn(".ai-review/tool-bundle/bundle.txt", files)

    def test_tool_bundle_skip_records_warning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            tool_dir = Path(td) / ".ai-review" / "tool-bundle"
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "head_sha": "0123456789abcdef",
                        "files": ["too-large.txt"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (tool_dir / "too-large.txt").write_bytes(b"x" * (100 * 1024 + 1))

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            warnings_txt = Path(td) / ".ai-review" / "warnings.txt"
            self.assertTrue(warnings_txt.is_file())
            warn = warnings_txt.read_text(encoding="utf-8")
            self.assertIn("tool_bundle_file_skipped", warn)
            self.assertIn("kind=size_limit_exceeded", warn)
            self.assertIn("too-large.txt", warn)

    def test_tool_bundle_decode_errors_count_toward_scan_limits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            tool_dir = Path(td) / ".ai-review" / "tool-bundle"
            tool_dir.mkdir(parents=True, exist_ok=True)
            names = [f"b{i:03d}.txt" for i in range(201)]
            (tool_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "head_sha": "0123456789abcdef",
                        "files": names,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            for n in names:
                (tool_dir / n).write_bytes(b"\xff")

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            warnings_txt = Path(td) / ".ai-review" / "warnings.txt"
            self.assertTrue(warnings_txt.is_file())
            warn = warnings_txt.read_text(encoding="utf-8")
            self.assertIn("tool_bundle_processing_stopped", warn)
            self.assertIn("kind=max_files_exceeded", warn)
            self.assertNotIn("b200.txt", warn)

    def test_tool_bundle_invalid_src_does_not_persist_src(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode(fake_opencode)

            tool_dir = Path(td) / ".ai-review" / "tool-bundle"
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "head_sha": "0123456789abcdef",
                        "files": ["bundle.txt"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            secret = "TOKEN_ABC123"
            (tool_dir / "bundle.txt").write_text(
                f"# SRC: ../../secrets/{secret}\nL1: x\n",
                encoding="utf-8",
            )

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 0, msg=(p.stdout + "\n" + p.stderr))

            warnings_txt = Path(td) / ".ai-review" / "warnings.txt"
            self.assertTrue(warnings_txt.is_file())
            warn = warnings_txt.read_text(encoding="utf-8")
            self.assertIn("tool_bundle_src_skipped", warn)
            self.assertIn("kind=invalid_src", warn)
            self.assertIn("bundle.txt", warn)
            self.assertNotIn(secret, warn)

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

    def test_questions_create_rerun_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_blocked_with_question(fake_opencode)

            p = run_cli(
                [
                    "review",
                    "--repo",
                    "owner/name",
                    "--pr",
                    "123",
                    "--hybrid-aspect",
                    "correctness",
                    "--hybrid-allowlist",
                    "docs/**/*.md",
                ],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 1, msg=(p.stdout + "\n" + p.stderr))

            rerun_dir = Path(td) / ".ai-review" / "re-run"
            self.assertTrue(rerun_dir.is_dir())
            plan_files = sorted(rerun_dir.glob("*/plan.json"))
            self.assertEqual(len(plan_files), 1)

            plan = json.loads(plan_files[0].read_text(encoding="utf-8"))
            self.assertEqual(plan.get("question_aspects"), ["correctness"])
            self.assertIn(
                "--hybrid-aspect correctness",
                str(plan.get("recommended_command", "")),
            )

    def test_questions_without_allowlist_skip_rerun_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_blocked_with_question(fake_opencode)

            p = run_cli(
                [
                    "review",
                    "--repo",
                    "owner/name",
                    "--pr",
                    "123",
                    "--hybrid-aspect",
                    "correctness",
                ],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 1, msg=(p.stdout + "\n" + p.stderr))

            rerun_dir = Path(td) / ".ai-review" / "re-run"
            self.assertFalse(rerun_dir.exists())

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

    def test_fetch_input_failure_clears_stale_review_summary(self) -> None:
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

            state_path = Path(td) / "fake-gh-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "head_ref_oid_sequence": [
                            "0123456789abcdef",
                            "fedcba9876543210",
                        ]
                    }
                ),
                encoding="utf-8",
            )

            p2 = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p2.returncode, 2, msg=(p2.stdout + "\n" + p2.stderr))
            self.assertFalse(summary_json.exists())
            self.assertFalse(summary_md.exists())

    def test_invalid_hybrid_allowlist_clears_stale_review_summary(self) -> None:
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

            p2 = run_cli(
                [
                    "review",
                    "--repo",
                    "owner/name",
                    "--pr",
                    "123",
                    "--hybrid-aspect",
                    "correctness",
                    "--hybrid-allowlist",
                    "../**/*",
                ],
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

    def test_post_summary_fails_when_head_moved_before_post(self) -> None:
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
            self.assertEqual(p.returncode, 2, msg=(p.stdout + "\n" + p.stderr))

            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 0)

            run_json = Path(td) / ".ai-review" / "run.json"
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("status"), "exec_failure")
            self.assertIn(
                "PR head changed before summary posting",
                payload.get("error", {}).get("message", ""),
            )
            out_dir = Path(td) / ".ai-review"
            self.assertFalse((out_dir / "review-summary.json").exists())
            self.assertFalse((out_dir / "review-summary.md").exists())

    def test_post_summary_fails_when_head_moves_during_post(self) -> None:
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
                            "0123456789abcdef",
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
            self.assertEqual(p.returncode, 2, msg=(p.stdout + "\n" + p.stderr))

            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 0)

            run_json = Path(td) / ".ai-review" / "run.json"
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("status"), "exec_failure")
            self.assertIn(
                "PR head changed; skip stale summary mutation",
                payload.get("error", {}).get("message", ""),
            )

            out_dir = Path(td) / ".ai-review"
            self.assertFalse((out_dir / "review-summary.json").exists())
            self.assertFalse((out_dir / "review-summary.md").exists())

    def test_post_summary_generic_post_failure_keeps_summary_artifacts(self) -> None:
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
                        "post_comment_error_message": "Internal Server Error",
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
            self.assertEqual(p.returncode, 2, msg=(p.stdout + "\n" + p.stderr))

            out_dir = Path(td) / ".ai-review"
            self.assertTrue((out_dir / "review-summary.json").exists())
            self.assertTrue((out_dir / "review-summary.md").exists())

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

    def test_post_summary_recovers_after_two_sequential_marker_deletions(self) -> None:
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
                            {
                                "id": 3,
                                "body": "<!-- killer-7:summary:v1 -->\nold-3",
                                "user": {"login": "owner"},
                            },
                        ],
                        "next_id": 4,
                        "patch_not_found_ids": [3, 2],
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

    def test_post_summary_keeps_one_comment_when_keep_id_deleted_before_dedupe(
        self,
    ) -> None:
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
                        "delete_on_list_call": 4,
                        "delete_on_list_comment_id": 2,
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

    def test_post_summary_rededupes_when_duplicate_appears_after_first_dedupe(
        self,
    ) -> None:
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
                        "add_marker_on_list_call": 5,
                        "add_marker_author": "owner",
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

    def test_post_summary_recovers_when_keep_deleted_during_second_dedupe(
        self,
    ) -> None:
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
                        "add_marker_on_list_call": 5,
                        "add_marker_author": "owner",
                        "delete_other_on_delete_comment_id": 3,
                        "delete_other_target_comment_id": 2,
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

    def test_inline_posts_even_when_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_blocked(fake_opencode)

            p = run_cli(
                ["review", "--repo", "owner/name", "--pr", "123", "--inline"],
                cwd=td,
                gh_bin=str(fake_gh),
                opencode_bin=str(fake_opencode),
            )
            self.assertEqual(p.returncode, 1, msg=(p.stdout + "\n" + p.stderr))

            state_path = Path(td) / "fake-gh-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 1)

            review_comments = state.get("review_comments", [])
            self.assertEqual(len(review_comments), 1)
            body = review_comments[0].get("body", "")
            self.assertIn("<!-- killer-7:inline:v1 fp=", body)
            self.assertEqual(review_comments[0].get("path"), "hello.txt")

    def test_post_summary_stale_head_overrides_blocked_result(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)
            fake_opencode = Path(td) / "fake-opencode"
            _write_fake_opencode_blocked(fake_opencode)

            state_path = Path(td) / "fake-gh-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "comments": [],
                        "next_id": 1,
                        "head_ref_oid_sequence": [
                            "0123456789abcdef",
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
            self.assertEqual(p.returncode, 2, msg=(p.stdout + "\n" + p.stderr))

            run_json = Path(td) / ".ai-review" / "run.json"
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("status"), "exec_failure")
            self.assertIn(
                "PR head changed before summary posting",
                payload.get("error", {}).get("message", ""),
            )

            out_dir = Path(td) / ".ai-review"
            self.assertFalse((out_dir / "review-summary.json").exists())
            self.assertFalse((out_dir / "review-summary.md").exists())

            state = json.loads(state_path.read_text(encoding="utf-8"))
            comments = state.get("comments", [])
            self.assertEqual(len(comments), 0)

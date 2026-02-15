from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from killer_7.artifacts import ensure_artifacts_dir
from killer_7.errors import BlockedError, ExecFailureError
from killer_7.llm.opencode_runner import OpenCodeRunner


def _git_init(td: str) -> None:
    subprocess.run(
        ["git", "init", "-q"],
        cwd=td,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _write_fake_opencode_ok(path: Path, *, payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    path.write_text(
        f"""#!/usr/bin/env python3
import json
import sys

_ = sys.stdin.read()

args = sys.argv[1:]
if len(args) < 1 or args[0] != "run":
    sys.stderr.write("fake opencode: unsupported args\\n")
    raise SystemExit(2)

try:
    i = args.index("--format")
except ValueError:
    sys.stderr.write("fake opencode: missing --format\\n")
    raise SystemExit(2)

if i + 1 >= len(args) or args[i + 1] != "json":
    sys.stderr.write("fake opencode: expected --format json\\n")
    raise SystemExit(2)

events = [
    {{"type": "log", "part": {{"text": "hello"}}}},
    {{"type": "text", "part": {{"text": {text!r}}}}},
]

for e in events:
    sys.stdout.write(json.dumps(e, ensure_ascii=False) + "\\n")

raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_ok_with_tool_use(path: Path, *, bash_command: str) -> None:
    final = json.dumps({"ok": True}, ensure_ascii=False)
    path.write_text(
        f"""#!/usr/bin/env python3
import json
import sys

_ = sys.stdin.read()

events = [
    {{
        "type": "tool_use",
        "timestamp": 2,
        "sessionID": "ses_x",
        "part": {{
            "type": "tool",
            "callID": "call_1",
            "tool": "bash",
            "state": {{
                "status": "completed",
                "input": {{"command": {bash_command!r}}},
                "output": "ok",
                "title": "",
                "metadata": {{"exit": 0}},
                "time": {{"start": 1, "end": 2}},
                "attachments": [],
            }},
        }},
    }},
    {{"type": "text", "part": {{"text": {final!r}}}}},
]

for e in events:
    sys.stdout.write(json.dumps(e, ensure_ascii=False) + "\\n")

raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_ok_with_read(path: Path, *, file_path: str) -> None:
    final = json.dumps({"ok": True}, ensure_ascii=False)
    path.write_text(
        f"""#!/usr/bin/env python3
import json
import sys

_ = sys.stdin.read()

events = [
    {{
        "type": "tool_use",
        "timestamp": 2,
        "sessionID": "ses_x",
        "part": {{
            "type": "tool",
            "callID": "call_1",
            "tool": "read",
            "state": {{
                "status": "completed",
                "input": {{"filePath": {file_path!r}, "offset": 1, "limit": 2}},
                "output": "",
                "title": "",
                "metadata": {{}},
                "time": {{"start": 1, "end": 2}},
                "attachments": [],
            }},
        }},
    }},
    {{"type": "text", "part": {{"text": {final!r}}}}},
]

for e in events:
    sys.stdout.write(json.dumps(e, ensure_ascii=False) + "\\n")

raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_ok_with_two_tool_uses(path: Path, *, file_path: str) -> None:
    final = json.dumps({"ok": True}, ensure_ascii=False)
    path.write_text(
        f"""#!/usr/bin/env python3
import json
import sys

_ = sys.stdin.read()

events = [
    {{
        "type": "tool_use",
        "timestamp": 2,
        "sessionID": "ses_x",
        "part": {{
            "type": "tool",
            "callID": "call_1",
            "tool": "read",
            "state": {{
                "status": "completed",
                "input": {{"filePath": {file_path!r}, "offset": 1, "limit": 1}},
                "output": "",
                "title": "",
                "metadata": {{}},
                "time": {{"start": 1, "end": 2}},
                "attachments": [],
            }},
        }},
    }},
    {{
        "type": "tool_use",
        "timestamp": 3,
        "sessionID": "ses_x",
        "part": {{
            "type": "tool",
            "callID": "call_2",
            "tool": "read",
            "state": {{
                "status": "completed",
                "input": {{"filePath": {file_path!r}, "offset": 2, "limit": 1}},
                "output": "",
                "title": "",
                "metadata": {{}},
                "time": {{"start": 2, "end": 3}},
                "attachments": [],
            }},
        }},
    }},
    {{"type": "text", "part": {{"text": {final!r}}}}},
]

for e in events:
    sys.stdout.write(json.dumps(e, ensure_ascii=False) + "\\n")

raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_ok_with_glob(path: Path) -> None:
    final = json.dumps({"ok": True}, ensure_ascii=False)
    path.write_text(
        f"""#!/usr/bin/env python3
import json
import sys

_ = sys.stdin.read()

events = [
    {{
        "type": "tool_use",
        "timestamp": 2,
        "sessionID": "ses_x",
        "part": {{
            "type": "tool",
            "callID": "call_1",
            "tool": "glob",
            "state": {{
                "status": "completed",
                "input": {{"path": ".", "pattern": "*.py"}},
                "output": "",
                "title": "",
                "metadata": {{}},
                "time": {{"start": 1, "end": 2}},
                "attachments": [],
            }},
        }},
    }},
    {{"type": "text", "part": {{"text": {final!r}}}}},
]

for e in events:
    sys.stdout.write(json.dumps(e, ensure_ascii=False) + "\\n")

raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_ok_with_glob_path(path: Path, *, base_path: str) -> None:
    final = json.dumps({"ok": True}, ensure_ascii=False)
    path.write_text(
        f"""#!/usr/bin/env python3
import json
import sys

_ = sys.stdin.read()

events = [
    {{
        "type": "tool_use",
        "timestamp": 2,
        "sessionID": "ses_x",
        "part": {{
            "type": "tool",
            "callID": "call_1",
            "tool": "glob",
            "state": {{
                "status": "completed",
                "input": {{"path": {base_path!r}, "pattern": "*.py"}},
                "output": "",
                "title": "",
                "metadata": {{}},
                "time": {{"start": 1, "end": 2}},
                "attachments": [],
            }},
        }},
    }},
    {{"type": "text", "part": {{"text": {final!r}}}}},
]

for e in events:
    sys.stdout.write(json.dumps(e, ensure_ascii=False) + "\\n")

raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_ok_with_grep(
    path: Path, *, pattern: str, include: str
) -> None:
    final = json.dumps({"ok": True}, ensure_ascii=False)
    path.write_text(
        f"""#!/usr/bin/env python3
import json
import sys

_ = sys.stdin.read()

events = [
    {{
        "type": "tool_use",
        "timestamp": 2,
        "sessionID": "ses_x",
        "part": {{
            "type": "tool",
            "callID": "call_1",
            "tool": "grep",
            "state": {{
                "status": "completed",
                "input": {{"path": ".", "pattern": {pattern!r}, "include": {include!r}}},
                "output": "",
                "title": "",
                "metadata": {{}},
                "time": {{"start": 1, "end": 2}},
                "attachments": [],
            }},
        }},
    }},
    {{"type": "text", "part": {{"text": {final!r}}}}},
]

for e in events:
    sys.stdout.write(json.dumps(e, ensure_ascii=False) + "\\n")

raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_invalid_jsonl(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import sys

_ = sys.stdin.read()

sys.stdout.write('{"type": "text", "part": {"text": "{not json}"}}\n')
sys.stdout.write('{this is not valid json\n')
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_invalid_final_json(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import sys

_ = sys.stdin.read()

sys.stdout.write(json.dumps({"type": "text", "part": {"text": "not-json"}}) + "\n")
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_nonzero(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import sys

_ = sys.stdin.read()

sys.stderr.write("boom\n")
raise SystemExit(3)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_fake_opencode_sleep(path: Path, *, seconds: float) -> None:
    path.write_text(
        f"""#!/usr/bin/env python3
import time

import sys

_ = sys.stdin.read()

time.sleep({seconds})
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


class TestOpenCodeRunner(unittest.TestCase):
    def test_success_writes_viewpoint_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok(fake, payload={"ok": True, "n": 1})

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            res = runner.run_viewpoint(
                out_dir=out_dir,
                viewpoint="Correctness",
                message="hello",
            )
            self.assertEqual(res["viewpoint"], "Correctness")

            p = Path(str(res["result_path"]))
            self.assertTrue(p.is_file())
            payload = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"ok": True, "n": 1})

    def test_explore_mode_writes_stdout_jsonl_and_tool_trace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok_with_tool_use(
                fake, bash_command="git --no-pager diff --no-ext-diff"
            )

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            _ = runner.run_viewpoint(
                out_dir=out_dir,
                viewpoint="Correctness",
                message="hello",
                env={"KILLER7_EXPLORE": "1"},
            )

            matches = list(
                (Path(out_dir) / "opencode").glob("correctness-*/stdout.jsonl")
            )
            self.assertTrue(matches)
            self.assertTrue(matches[0].is_file())

            traces = list(
                (Path(out_dir) / "opencode").glob("correctness-*/tool-trace.jsonl")
            )
            self.assertTrue(traces)
            self.assertTrue(traces[0].is_file())

    def test_explore_mode_stdout_jsonl_redacts_tool_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok_with_glob_path(fake, base_path=str(Path(td)))

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            _ = runner.run_viewpoint(
                out_dir=out_dir,
                viewpoint="Correctness",
                message="hello",
                env={"KILLER7_EXPLORE": "1"},
            )

            matches = list(
                (Path(out_dir) / "opencode").glob("correctness-*/stdout.jsonl")
            )
            self.assertTrue(matches)
            txt = matches[0].read_text(encoding="utf-8")
            self.assertIn('"tool": "glob"', txt)
            self.assertIn('"path": "."', txt)

    def test_explore_repo_root_does_not_expand_when_out_dir_is_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            parent = str(Path(td).parent)
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok_with_glob_path(fake, base_path=parent)

            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            with self.assertRaises(BlockedError):
                runner.run_viewpoint(
                    out_dir=td,
                    viewpoint="Correctness",
                    message="hello",
                    env={"KILLER7_EXPLORE": "1"},
                )

    def test_explore_mode_redacts_grep_pattern_in_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok_with_grep(
                fake,
                pattern="API_KEY=supersecret",
                include="*.py",
            )

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            _ = runner.run_viewpoint(
                out_dir=out_dir,
                viewpoint="Correctness",
                message="hello",
                env={"KILLER7_EXPLORE": "1"},
            )

            traces = list(
                (Path(out_dir) / "opencode").glob("correctness-*/tool-trace.jsonl")
            )
            self.assertTrue(traces)
            trace_txt = traces[0].read_text(encoding="utf-8")
            self.assertNotIn("API_KEY=supersecret", trace_txt)
            self.assertIn("API_KEY=<REDACTED>", trace_txt)

            stdouts = list(
                (Path(out_dir) / "opencode").glob("correctness-*/stdout.jsonl")
            )
            self.assertTrue(stdouts)
            stdout_txt = stdouts[0].read_text(encoding="utf-8")
            self.assertNotIn("API_KEY=supersecret", stdout_txt)
            self.assertIn("API_KEY=<REDACTED>", stdout_txt)

    def test_explore_mode_blocks_forbidden_git_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok_with_tool_use(
                fake, bash_command="git push origin HEAD"
            )

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            with self.assertRaises(BlockedError):
                runner.run_viewpoint(
                    out_dir=out_dir,
                    viewpoint="Security",
                    message="hello",
                    env={"KILLER7_EXPLORE": "1"},
                )

            matches = list((Path(out_dir) / "opencode").glob("security-*/error.json"))
            self.assertTrue(matches)
            self.assertTrue(matches[0].is_file())

            stdout_txt = matches[0].parent / "stdout.txt"
            stderr_txt = matches[0].parent / "stderr.txt"
            self.assertFalse(stdout_txt.exists())
            self.assertFalse(stderr_txt.exists())

    def test_host_env_explore_does_not_enable_explore_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok_with_tool_use(
                fake, bash_command="git push origin HEAD"
            )

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)

            old = os.environ.get("KILLER7_EXPLORE")
            os.environ["KILLER7_EXPLORE"] = "1"
            try:
                res = runner.run_viewpoint(
                    out_dir=out_dir,
                    viewpoint="Correctness",
                    message="hello",
                )
            finally:
                if old is None:
                    os.environ.pop("KILLER7_EXPLORE", None)
                else:
                    os.environ["KILLER7_EXPLORE"] = old

            p = Path(str(res["result_path"]))
            self.assertTrue(p.is_file())
            traces = list(
                (Path(out_dir) / "opencode").glob("correctness-*/tool-trace.jsonl")
            )
            self.assertFalse(traces)

    def test_explore_mode_writes_tool_bundle_from_read(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            target = Path(td) / "x.txt"
            target.write_text("a\nB\nC\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "x.txt"],
                cwd=td,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok_with_read(fake, file_path=str(target))

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            _ = runner.run_viewpoint(
                out_dir=out_dir,
                viewpoint="Readability",
                message="hello",
                env={"KILLER7_EXPLORE": "1"},
            )

            bundles = list(
                (Path(out_dir) / "opencode").glob("readability-*/tool-bundle.txt")
            )
            self.assertTrue(bundles)
            txt = bundles[0].read_text(encoding="utf-8")
            self.assertIn("# SRC: x.txt", txt)
            self.assertIn("L1: <redacted>", txt)
            self.assertIn("L2: <redacted>", txt)

    def test_explore_mode_blocks_reading_dot_git(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            dotgit = Path(td) / ".git"
            dotgit.mkdir(parents=True, exist_ok=True)
            target = dotgit / "config"
            target.write_text(
                "[core]\n\trepositoryformatversion = 0\n", encoding="utf-8"
            )

            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok_with_read(fake, file_path=str(target))

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            with self.assertRaises(BlockedError):
                runner.run_viewpoint(
                    out_dir=out_dir,
                    viewpoint="Security",
                    message="hello",
                    env={"KILLER7_EXPLORE": "1"},
                )

            matches = list((Path(out_dir) / "opencode").glob("security-*/error.json"))
            self.assertTrue(matches)

            stdout_txt = matches[0].parent / "stdout.txt"
            stderr_txt = matches[0].parent / "stderr.txt"
            self.assertFalse(stdout_txt.exists())
            self.assertFalse(stderr_txt.exists())

    def test_explore_mode_limits_tool_calls(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            target = Path(td) / "x.txt"
            target.write_text("a\nB\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "x.txt"],
                cwd=td,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok_with_two_tool_uses(fake, file_path=str(target))

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            with self.assertRaises(BlockedError):
                runner.run_viewpoint(
                    out_dir=out_dir,
                    viewpoint="Testing",
                    message="hello",
                    env={
                        "KILLER7_EXPLORE": "1",
                        "KILLER7_EXPLORE_MAX_TOOL_CALLS": "1",
                    },
                )

            matches = list((Path(out_dir) / "opencode").glob("testing-*/error.json"))
            self.assertTrue(matches)

    def test_explore_mode_allows_glob_tool(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok_with_glob(fake)

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            _ = runner.run_viewpoint(
                out_dir=out_dir,
                viewpoint="Refactoring",
                message="hello",
                env={"KILLER7_EXPLORE": "1"},
            )

            traces = list(
                (Path(out_dir) / "opencode").glob("refactoring-*/tool-trace.jsonl")
            )
            self.assertTrue(traces)
            txt = traces[0].read_text(encoding="utf-8")
            self.assertIn('"tool": "glob"', txt)

    def test_explore_mode_limits_total_read_lines_across_tool_calls(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            target = Path(td) / "x.txt"
            target.write_text("a\nB\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "x.txt"],
                cwd=td,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_ok_with_two_tool_uses(fake, file_path=str(target))

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            with self.assertRaises(BlockedError):
                runner.run_viewpoint(
                    out_dir=out_dir,
                    viewpoint="Testing",
                    message="hello",
                    env={
                        "KILLER7_EXPLORE": "1",
                        "KILLER7_EXPLORE_MAX_READ_LINES": "1",
                    },
                )

            matches = list((Path(out_dir) / "opencode").glob("testing-*/error.json"))
            self.assertTrue(matches)

    def test_explore_mode_invalid_jsonl_does_not_persist_raw_stdio(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            _git_init(td)
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_invalid_jsonl(fake)

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            with self.assertRaises(ExecFailureError):
                runner.run_viewpoint(
                    out_dir=out_dir,
                    viewpoint="Testing",
                    message="hi",
                    env={"KILLER7_EXPLORE": "1"},
                )

            matches = list((Path(out_dir) / "opencode").glob("testing-*/error.json"))
            self.assertTrue(matches)
            err = matches[0]
            self.assertTrue(err.is_file())

            stdout_txt = err.parent / "stdout.txt"
            stderr_txt = err.parent / "stderr.txt"
            self.assertFalse(stdout_txt.exists())
            self.assertFalse(stderr_txt.exists())

    def test_invalid_jsonl_raises_and_writes_error_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_invalid_jsonl(fake)

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            with self.assertRaises(ExecFailureError):
                runner.run_viewpoint(out_dir=out_dir, viewpoint="Testing", message="hi")

            matches = list((Path(out_dir) / "opencode").glob("testing-*/error.json"))
            self.assertTrue(matches)
            err = matches[0]
            self.assertTrue(err.is_file())

            stdout_txt = err.parent / "stdout.txt"
            stderr_txt = err.parent / "stderr.txt"
            self.assertTrue(stdout_txt.is_file())
            self.assertTrue(stderr_txt.is_file())

    def test_invalid_final_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_invalid_final_json(fake)

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            with self.assertRaises(ExecFailureError):
                runner.run_viewpoint(
                    out_dir=out_dir, viewpoint="Security", message="hi"
                )

            matches = list((Path(out_dir) / "opencode").glob("security-*/error.json"))
            self.assertTrue(matches)
            err = matches[0]
            self.assertTrue(err.is_file())

    def test_nonzero_exit_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_nonzero(fake)

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            with self.assertRaises(ExecFailureError):
                runner.run_viewpoint(out_dir=out_dir, viewpoint="Perf", message="hi")

            matches = list((Path(out_dir) / "opencode").glob("perf-*/error.json"))
            self.assertTrue(matches)
            err = matches[0]
            self.assertTrue(err.is_file())

    def test_timeout_raises_and_writes_error_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "fake-opencode"
            _write_fake_opencode_sleep(fake, seconds=2.0)

            out_dir = ensure_artifacts_dir(td)
            runner = OpenCodeRunner(bin_path=str(fake), timeout_s=10)
            with self.assertRaises(ExecFailureError):
                runner.run_viewpoint(
                    out_dir=out_dir,
                    viewpoint="Refactor",
                    message="hi",
                    timeout_s=1,
                )

            matches = list((Path(out_dir) / "opencode").glob("refactor-*/error.json"))
            self.assertTrue(matches)
            err = matches[0]
            self.assertTrue(err.is_file())


if __name__ == "__main__":
    raise SystemExit(unittest.main())

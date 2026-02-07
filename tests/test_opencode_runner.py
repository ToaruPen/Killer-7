from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from killer_7.artifacts import ensure_artifacts_dir
from killer_7.errors import ExecFailureError
from killer_7.llm.opencode_runner import OpenCodeRunner


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

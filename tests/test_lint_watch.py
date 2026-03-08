from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from killer_7.lint_watch import (
    FileEvent,
    detect_events,
    lint_targets_for_events,
    resolve_ruff_command,
    run_ruff,
    snapshot_watch_state,
)


class TestLintWatch(unittest.TestCase):
    def test_script_help_runs_from_repo_root(self) -> None:
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(  # noqa: S603
            [sys.executable, "scripts/codex-watch-lint.py", "--help"],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Watch Killer-7 source files", result.stdout)

    def test_script_help_runs_outside_repo_root(self) -> None:
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(  # noqa: S603
                [
                    sys.executable,
                    str(root / "scripts" / "codex-watch-lint.py"),
                    "--help",
                ],
                check=False,
                cwd=tmp,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Watch Killer-7 source files", result.stdout)

    def test_snapshot_tracks_python_sources_and_repo_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "killer_7").mkdir()
            (root / "tests").mkdir()
            (root / "scripts").mkdir()
            (root / "killer_7" / "cli.py").write_text("print('x')\n", encoding="utf-8")
            (root / "tests" / "test_cli.py").write_text(
                "print('x')\n", encoding="utf-8"
            )
            (root / "scripts" / "tool.py").write_text("print('x')\n", encoding="utf-8")
            (root / "scripts" / "tool.sh").write_text("echo x\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
            (root / "README.md").write_text("# x\n", encoding="utf-8")

            snapshot = snapshot_watch_state(root)

            self.assertEqual(
                set(snapshot),
                {
                    "killer_7/cli.py",
                    "tests/test_cli.py",
                    "scripts/tool.py",
                    "pyproject.toml",
                },
            )

    def test_detect_events_reports_modifications_and_deletions(self) -> None:
        events = detect_events(
            {"killer_7/cli.py": 1, "tests/test_cli.py": 2},
            {"killer_7/cli.py": 3, "scripts/tool.py": 4},
        )

        self.assertEqual(
            events,
            (
                FileEvent(path="killer_7/cli.py", kind="modified"),
                FileEvent(path="scripts/tool.py", kind="modified"),
                FileEvent(path="tests/test_cli.py", kind="deleted"),
            ),
        )

    def test_lint_targets_are_repo_wide_for_config_or_deletes(self) -> None:
        self.assertEqual(
            lint_targets_for_events(
                (FileEvent(path="pyproject.toml", kind="modified"),)
            ),
            ("killer_7", "tests", "scripts"),
        )
        self.assertEqual(
            lint_targets_for_events(
                (FileEvent(path="killer_7/cli.py", kind="deleted"),)
            ),
            ("killer_7", "tests", "scripts"),
        )

    def test_lint_targets_use_changed_python_files_when_safe(self) -> None:
        targets = lint_targets_for_events(
            (
                FileEvent(path="killer_7/cli.py", kind="modified"),
                FileEvent(path="tests/test_cli.py", kind="modified"),
            )
        )

        self.assertEqual(targets, ("killer_7/cli.py", "tests/test_cli.py"))

    def test_resolve_ruff_command_prefers_binary_then_python_module(self) -> None:
        def fake_run(args: list[str], **_kwargs: object):
            if args[:4] == [sys.executable, "-m", "ruff", "--version"]:
                return _Completed(returncode=0)
            raise AssertionError(f"unexpected args: {args}")

        self.assertEqual(
            resolve_ruff_command(run=fake_run), (sys.executable, "-m", "ruff")
        )

        def fake_run_python(args: list[str], **_kwargs: object):
            if args[:4] == [sys.executable, "-m", "ruff", "--version"]:
                raise FileNotFoundError
            if args[:2] == ["ruff", "--version"]:
                return _Completed(returncode=0)
            raise AssertionError(f"unexpected args: {args}")

        self.assertEqual(
            resolve_ruff_command(run=fake_run_python),
            ("ruff",),
        )

    def test_resolve_ruff_command_matches_current_interpreter(self) -> None:
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-c",
                (
                    "from killer_7.lint_watch import resolve_ruff_command; "
                    "print('\\n'.join(resolve_ruff_command()))"
                ),
            ],
            check=False,
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip().splitlines(),
            [sys.executable, "-m", "ruff"],
        )

    def test_run_ruff_executes_check_then_format_with_cache_disabled(self) -> None:
        calls: list[tuple[list[str], str, str | None]] = []

        def fake_run(args: list[str], **kwargs: object):
            env = kwargs.get("env")
            cwd = kwargs.get("cwd")
            calls.append(
                (
                    args,
                    str(cwd),
                    None if env is None else env.get("RUFF_NO_CACHE"),
                )
            )
            return _Completed(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            exit_code = run_ruff(
                Path(tmp),
                ("ruff",),
                ("killer_7/cli.py",),
                run=fake_run,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            calls,
            [
                (["ruff", "check", "killer_7/cli.py"], tmp, "1"),
                (["ruff", "format", "--check", "killer_7/cli.py"], tmp, "1"),
            ],
        )

    def test_main_rejects_non_positive_interval(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            from killer_7.lint_watch import main

            main(["--interval", "0"])

        self.assertEqual(ctx.exception.code, 2)


class _Completed:
    def __init__(self, *, returncode: int) -> None:
        self.returncode = returncode


if __name__ == "__main__":
    raise SystemExit(unittest.main())

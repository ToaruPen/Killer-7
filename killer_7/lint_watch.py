from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

WATCH_DIRS: tuple[str, ...] = ("killer_7", "tests", "scripts")
WATCH_FILES: tuple[str, ...] = (
    "pyproject.toml",
    "requirements-dev.txt",
    "requirements-killer7.txt",
)
REPO_WIDE_TARGETS: tuple[str, ...] = WATCH_DIRS


@dataclass(frozen=True)
class FileEvent:
    path: str
    kind: str


CompletedProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


def snapshot_watch_state(root: Path) -> dict[str, int]:
    state: dict[str, int] = {}
    for rel_path in WATCH_FILES:
        path = root / rel_path
        if path.is_file():
            state[rel_path] = path.stat().st_mtime_ns
    for directory in WATCH_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if path.is_file():
                state[path.relative_to(root).as_posix()] = path.stat().st_mtime_ns
    return state


def detect_events(
    before: dict[str, int], after: dict[str, int]
) -> tuple[FileEvent, ...]:
    events: list[FileEvent] = []
    for path in sorted(set(before) | set(after)):
        if path not in after:
            events.append(FileEvent(path=path, kind="deleted"))
            continue
        if path not in before or before[path] != after[path]:
            events.append(FileEvent(path=path, kind="modified"))
    return tuple(events)


def lint_targets_for_events(events: Sequence[FileEvent]) -> tuple[str, ...]:
    if not events:
        return ()
    if any(event.kind == "deleted" for event in events):
        return REPO_WIDE_TARGETS
    changed_paths = {event.path for event in events}
    if changed_paths.intersection(WATCH_FILES):
        return REPO_WIDE_TARGETS
    return tuple(sorted(changed_paths))


def format_events(events: Sequence[FileEvent]) -> str:
    return ", ".join(f"{event.kind}:{event.path}" for event in events)


def resolve_ruff_command(
    run: CompletedProcessRunner = subprocess.run,
) -> tuple[str, ...]:
    candidates = ((sys.executable, "-m", "ruff"), ("ruff",))
    for command in candidates:
        try:
            result = run(
                [*command, "--version"],
                check=False,
                capture_output=True,
                text=True,
            )  # noqa: S603 - intentional local binary/module probe with shell=False
        except FileNotFoundError:
            continue
        if result.returncode == 0:
            return command
    raise RuntimeError(
        f"ruff is required for {sys.executable}. "
        "Install it with `python3 -m pip install -r requirements-dev.txt`."
    )


def run_ruff(
    root: Path,
    ruff_command: Sequence[str],
    targets: Sequence[str],
    run: CompletedProcessRunner = subprocess.run,
) -> int:
    env = dict(os.environ)
    env.setdefault("RUFF_NO_CACHE", "1")
    commands = (
        ("check", *targets),
        ("format", "--check", *targets),
    )
    for command in commands:
        result = run(
            [*ruff_command, *command],
            check=False,
            cwd=root,
            env=env,
            text=True,
        )  # noqa: S603 - intentional local Ruff exec with shell=False
        if result.returncode != 0:
            return result.returncode
    return 0


def watch_loop(root: Path, *, interval: float, once: bool) -> int:
    snapshot = snapshot_watch_state(root)
    ruff_command = resolve_ruff_command()
    print(
        f"[lint-watch] watching {root} every {interval:.2f}s "
        f"({len(snapshot)} tracked paths)",
        flush=True,
    )
    while True:
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("[lint-watch] stopped", flush=True)
            return 130
        current = snapshot_watch_state(root)
        events = detect_events(snapshot, current)
        snapshot = current
        if not events:
            continue
        targets = lint_targets_for_events(events)
        print(f"[lint-watch] detected {format_events(events)}", flush=True)
        print(f"[lint-watch] running ruff on: {', '.join(targets)}", flush=True)
        exit_code = run_ruff(root, ruff_command, targets)
        if exit_code == 0:
            print("[lint-watch] ok", flush=True)
        else:
            print(
                f"[lint-watch] failed with exit code {exit_code}; continuing to watch",
                flush=True,
            )
        if once:
            return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Watch Killer-7 source files and run Ruff after local file writes."
        )
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.75,
        help="Polling interval in seconds (default: 0.75).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Exit after the first detected change has been checked.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be greater than 0")
    root = Path.cwd()
    return watch_loop(root, interval=args.interval, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())

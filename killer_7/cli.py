"""CLI entrypoint for Killer-7."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .artifacts import write_pr_input_artifacts
from .errors import BlockedError, ExecFailureError, ExitCode
from .github.pr_input import fetch_pr_input


def now_utc_z() -> str:
    """Return ISO 8601 UTC timestamp without milliseconds."""

    return (
        datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


@dataclass(frozen=True)
class ParserExit(Exception):
    code: int
    message: str = ""


class ThrowingArgumentParser(argparse.ArgumentParser):
    def exit(self, status: int = 0, message: str | None = None) -> None:  # type: ignore[override]
        if message:
            self._print_message(message, sys.stderr if status else sys.stdout)
        raise ParserExit(status, message or "")

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self._print_message(f"{self.prog}: error: {message}\n", sys.stderr)
        raise ParserExit(2, f"{self.prog}: error: {message}\n")


def parse_repo(value: str) -> str:
    v = value.strip()
    if not v or "/" not in v:
        raise argparse.ArgumentTypeError("--repo must be in the form <owner/name>")
    parts = v.split("/")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("--repo must be in the form <owner/name>")
    owner, name = parts
    if not owner or not name:
        raise argparse.ArgumentTypeError("--repo must be in the form <owner/name>")
    return v


def parse_pr(value: str) -> int:
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--pr must be an integer") from exc
    if n < 1:
        raise argparse.ArgumentTypeError("--pr must be >= 1")
    return n


def build_parser() -> ThrowingArgumentParser:
    parser = ThrowingArgumentParser(prog="killer-7")
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="Run review for a GitHub PR")
    review.add_argument("--repo", required=True, type=parse_repo)
    review.add_argument("--pr", required=True, type=parse_pr)
    review.set_defaults(_handler=handle_review)

    return parser


def ensure_artifacts_dir(base_dir: str) -> str:
    out_dir = os.path.join(base_dir, ".ai-review")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def write_run_json(out_dir: str, payload: dict[str, Any]) -> None:
    path = os.path.join(out_dir, "run.json")
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        fh.write("\n")
    os.replace(tmp, path)


def handle_review(args: argparse.Namespace) -> dict[str, Any]:
    # Fetch PR input (diff + metadata) and write artifacts.
    out_dir = ensure_artifacts_dir(os.getcwd())
    pr_input = fetch_pr_input(repo=args.repo, pr=args.pr)
    artifacts = write_pr_input_artifacts(out_dir, pr_input)
    return {
        "action": "review",
        "repo": args.repo,
        "pr": args.pr,
        "head_sha": pr_input.head_sha,
        "artifacts": {
            "diff_patch": os.path.relpath(artifacts["diff_patch"], os.getcwd()),
            "changed_files_tsv": os.path.relpath(
                artifacts["changed_files_tsv"], os.getcwd()
            ),
            "meta_json": os.path.relpath(artifacts["meta_json"], os.getcwd()),
        },
    }


def main(argv: Iterable[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    started_at = now_utc_z()
    t0 = time.monotonic()

    exit_code: int = int(ExitCode.EXEC_FAILURE)
    status = "unknown"
    result: dict[str, Any] = {}
    error: dict[str, Any] | None = None

    try:
        parser = build_parser()
        args = parser.parse_args(argv_list)
        handler = getattr(args, "_handler", None)
        if handler is None:
            raise BlockedError("No handler configured for this command")
        result = handler(args)
        status = "ok"
        exit_code = int(ExitCode.SUCCESS)
    except ParserExit as exc:
        # argparse already printed usage/help.
        status = "help" if exc.code == 0 else "invalid_args"
        exit_code = int(ExitCode.SUCCESS if exc.code == 0 else ExitCode.EXEC_FAILURE)
        if exc.message:
            error = {"message": exc.message.strip("\n")}
    except BlockedError as exc:
        status = "blocked"
        exit_code = int(ExitCode.BLOCKED)
        error = {"message": str(exc)}
        print(f"[killer-7] BLOCKED: {exc}", file=sys.stderr)
    except ExecFailureError as exc:
        status = "exec_failure"
        exit_code = int(ExitCode.EXEC_FAILURE)
        error = {"message": str(exc)}
        print(f"[killer-7] ERROR: {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        status = "exec_failure"
        exit_code = int(ExitCode.EXEC_FAILURE)
        error = {"type": type(exc).__name__, "message": str(exc)}
        print(f"[killer-7] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        ended_at = now_utc_z()
        duration_ms = int((time.monotonic() - t0) * 1000)

        payload: dict[str, Any] = {
            "schema_version": 1,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_ms": duration_ms,
            "argv": argv_list,
            "cwd": os.getcwd(),
            "status": status,
            "exit_code": exit_code,
            "result": result,
        }
        if error is not None:
            payload["error"] = error

        try:
            out_dir = ensure_artifacts_dir(os.getcwd())
            write_run_json(out_dir, payload)
        except Exception as exc:  # noqa: BLE001
            # If we can't write artifacts, treat as execution failure.
            print(
                f"[killer-7] ERROR: failed to write artifacts: {exc}", file=sys.stderr
            )
            return int(ExitCode.EXEC_FAILURE)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI entrypoint for Killer-7."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NoReturn

from .artifacts import (
    write_allowlist_paths_json,
    write_content_warnings_json,
    write_context_bundle_txt,
    write_pr_input_artifacts,
    write_sot_md,
    write_warnings_txt,
)
from .errors import BlockedError, ExecFailureError, ExitCode
from .github.content import ContentWarning, GitHubContentFetcher
from .github.pr_input import fetch_pr_input
from .bundle.context_bundle import build_context_bundle
from .bundle.diff_parse import parse_diff_patch
from .sot.allowlist import default_sot_allowlist
from .sot.collect import build_sot_markdown
from .aspects.orchestrate import run_all_aspects


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
    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:  # type: ignore[override]
        if message:
            self._print_message(message, sys.stderr if status else sys.stdout)
        raise ParserExit(status, message or "")

    def error(self, message: str) -> NoReturn:  # type: ignore[override]
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

    # Collect SoT from PR branch (ref=head sha) using allowlist.
    allowlist = default_sot_allowlist()
    fetcher = GitHubContentFetcher()

    sot_paths: list[str] = []
    content_warning_objs: list[ContentWarning] = []

    try:
        sot_paths = fetcher.resolve_allowlist_paths(
            repo=args.repo, ref=pr_input.head_sha, allowlist=allowlist
        )
    except ExecFailureError as exc:
        # Allow the overall command to succeed even if SoT collection fails.
        # This matches AC3's intent: record a warning and continue.
        content_warning_objs.append(
            ContentWarning(
                kind="allowlist_resolve_failed",
                path="",
                message=str(exc),
            )
        )
        sot_paths = []

    allowlist_paths_json = write_allowlist_paths_json(out_dir, sot_paths)

    contents_by_path: dict[str, str] = {}
    try:
        fetched = fetcher.fetch_text_files(
            repo=args.repo, ref=pr_input.head_sha, paths=sot_paths
        )
        contents_by_path = dict(fetched.contents_by_path)
        content_warning_objs.extend(list(fetched.warnings))
    except ExecFailureError as exc:
        content_warning_objs.append(
            ContentWarning(
                kind="fetch_text_files_failed",
                path="",
                message=str(exc),
            )
        )
        contents_by_path = {}

    content_warnings_payload: list[object] = list(content_warning_objs)
    content_warnings_json = write_content_warnings_json(
        out_dir, content_warnings_payload
    )

    sot_md, sot_warnings = build_sot_markdown(contents_by_path, max_lines=250)
    sot_md_path = write_sot_md(out_dir, sot_md)

    # Build Context Bundle (diff excerpt + SoT bundle) within a 1500-line cap.
    # We reserve SoT lines first (max 250) and spend the remaining budget on the diff excerpt.
    sot_lines = len((sot_md or "").splitlines())
    diff_budget = max(0, 1500 - sot_lines)

    src_blocks, diff_parse_warnings = parse_diff_patch(pr_input.diff_patch)
    diff_bundle, context_bundle_warnings = build_context_bundle(
        src_blocks,
        max_total_lines=diff_budget,
        max_file_lines=400,
    )

    # Ensure the SoT bundle starts at a line boundary.
    diff_part = (diff_bundle or "").rstrip("\n")
    sot_part = sot_md or ""
    context_bundle_txt = (diff_part + "\n" + sot_part) if diff_part else sot_part
    context_bundle_path = write_context_bundle_txt(out_dir, context_bundle_txt)

    def one_line(value: object) -> str:
        s = "" if value is None else str(value)
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        s = s.replace("\n", "\\n")
        s = s.replace("\t", "\\t")
        return s

    warning_lines: list[str] = []
    warning_lines.extend(diff_parse_warnings)
    warning_lines.extend(context_bundle_warnings)
    warning_lines.extend(sot_warnings)
    for w in content_warning_objs:
        extra: list[str] = []
        if w.size_bytes is not None:
            extra.append(f"size_bytes={w.size_bytes}")
        if w.limit_bytes is not None:
            extra.append(f"limit_bytes={w.limit_bytes}")
        tail = (" " + " ".join(extra)) if extra else ""

        warning_lines.append(
            "content_warning"
            f" kind={one_line(w.kind)}"
            f" path={one_line(w.path)}"
            f" message={one_line(w.message)}{tail}"
        )
    warnings_txt_path = write_warnings_txt(out_dir, warning_lines)

    # Run all review aspects (Issue #8) in parallel and write aspect artifacts.
    # Keep scope_id deterministic and tied to the PR input.
    scope_id = f"{args.repo}#pr-{args.pr}@{pr_input.head_sha[:12]}"
    aspects_result = run_all_aspects(
        base_dir=os.getcwd(),
        scope_id=scope_id,
        context_bundle=diff_bundle,
        sot=sot_md,
        max_llm_calls=8,
        max_workers=8,
    )

    return {
        "action": "review",
        "repo": args.repo,
        "pr": args.pr,
        "head_sha": pr_input.head_sha,
        "scope_id": scope_id,
        "aspects": {
            "index_path": os.path.relpath(
                str(aspects_result["index_path"]), os.getcwd()
            ),
        },
        "artifacts": {
            "diff_patch": os.path.relpath(artifacts["diff_patch"], os.getcwd()),
            "changed_files_tsv": os.path.relpath(
                artifacts["changed_files_tsv"], os.getcwd()
            ),
            "meta_json": os.path.relpath(artifacts["meta_json"], os.getcwd()),
            "allowlist_paths_json": os.path.relpath(allowlist_paths_json, os.getcwd()),
            "content_warnings_json": os.path.relpath(
                content_warnings_json, os.getcwd()
            ),
            "sot_md": os.path.relpath(sot_md_path, os.getcwd()),
            "context_bundle_txt": os.path.relpath(context_bundle_path, os.getcwd()),
            "warnings_txt": os.path.relpath(warnings_txt_path, os.getcwd()),
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

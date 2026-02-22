"""CLI entrypoint for Killer-7."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NoReturn

from .artifacts import (
    atomic_write_json_secure,
    atomic_write_text_secure,
    write_allowlist_paths_json,
    write_aspect_evidence_json,
    write_aspect_policy_json,
    write_aspects_evidence_index_json,
    write_aspects_policy_index_json,
    write_content_warnings_json,
    write_context_bundle_txt,
    write_evidence_json,
    write_pr_input_artifacts,
    write_review_summary_json,
    write_review_summary_md,
    write_sot_md,
    write_tool_bundle_txt,
    write_tool_trace_jsonl,
    write_warnings_txt,
)
from .aspect_id import normalize_aspect
from .aspects.orchestrate import ASPECTS_V1, run_all_aspects
from .bundle.context_bundle import build_context_bundle
from .bundle.diff_parse import parse_diff_patch
from .errors import BlockedError, ExecFailureError, ExitCode
from .github.content import ContentWarning, GitHubContentFetcher
from .github.gh import GhClient
from .github.post_inline import post_inline_comments, raise_if_inline_blocked
from .github.post_summary import post_summary_comment
from .github.pr_input import fetch_pr_input
from .hybrid.policy import build_hybrid_policy
from .hybrid.re_run import write_questions_rerun_artifacts
from .llm.opencode_runner import opencode_artifacts_dir
from .report.format_md import format_review_summary_md
from .report.merge import merge_review_summary
from .sot.allowlist import default_sot_allowlist
from .sot.collect import build_sot_markdown
from .validate.evidence import (
    EVIDENCE_POLICY_V1,
    apply_evidence_policy_to_findings,
    parse_context_bundle_index,
    recompute_review_status,
)
from .validate.review_json import validate_review_summary_json


def _strip_machine_fields_from_findings(
    findings: list[dict[str, object]],
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for f in findings:
        item = dict(f)
        item.pop("verified", None)
        item.pop("original_priority", None)
        out.append(item)
    return out


def now_utc_z() -> str:
    """Return ISO 8601 UTC timestamp without milliseconds."""

    return (
        datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _normalize_tool_bundle_src_path(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return ""
    if len(p) > 4096:
        return ""
    p = p.replace("\\", "/")
    if "#" in p:
        return ""
    while p.startswith("./"):
        p = p[2:]
    if p.startswith("/"):
        return ""
    if re.match(r"^[A-Za-z]:", p):
        return ""
    parts = [seg for seg in p.split("/") if seg and seg != "."]
    if any(seg == ".." for seg in parts):
        return ""
    return "/".join(parts)


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


def parse_aspect(value: str) -> str:
    try:
        a = normalize_aspect(value)
    except ExecFailureError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if a not in ASPECTS_V1:
        valid = ", ".join(ASPECTS_V1)
        raise argparse.ArgumentTypeError(
            f"Unknown aspect: {value!r}. Valid aspects: {valid}"
        )
    return a


def parse_preset_name(value: str) -> str:
    try:
        key = normalize_aspect(value)
    except ExecFailureError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if key not in BUILTIN_PRESETS:
        choices = ", ".join(sorted(BUILTIN_PRESETS.keys()))
        raise argparse.ArgumentTypeError(
            f"Unknown preset: {value!r}. Available presets: {choices}"
        )
    return key


BUILTIN_PRESETS: dict[str, tuple[str, ...]] = {
    "minimal": ("correctness", "security"),
    "standard": ("correctness", "readability", "testing", "security"),
    "full": ASPECTS_V1,
}

DEFAULT_NO_SOT_ASPECTS: tuple[str, ...] = ()


def resolve_preset(name: str) -> tuple[str, ...]:
    preset = BUILTIN_PRESETS.get(name)
    if preset is None:
        choices = ", ".join(sorted(BUILTIN_PRESETS.keys()))
        raise ExecFailureError(f"Unknown preset: {name!r} (available: {choices})")
    return preset


def build_parser() -> ThrowingArgumentParser:
    parser = ThrowingArgumentParser(prog="killer-7")
    sub = parser.add_subparsers(dest="command", required=True)

    examples = """
Examples:
  killer-7 review --repo owner/name --pr 123

  # Run only one aspect
  killer-7 review --repo owner/name --pr 123 --aspect correctness

  # Run multiple aspects
  killer-7 review --repo owner/name --pr 123 --aspect correctness --aspect security

  # Run a builtin preset
  killer-7 review --repo owner/name --pr 123 --preset minimal

  # Post summary + inline comments (P0/P1)
  killer-7 review --repo owner/name --pr 123 --post --inline
""".strip("\n")

    review = sub.add_parser(
        "review",
        help="Run review for a GitHub PR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=examples,
    )
    review.add_argument("--repo", required=True, type=parse_repo, help="<owner/name>")
    review.add_argument("--pr", required=True, type=parse_pr, help="PR number")

    aspect_sel = review.add_mutually_exclusive_group()
    aspect_sel.add_argument(
        "--aspect",
        action="append",
        default=[],
        type=parse_aspect,
        metavar="NAME",
        help=(
            "Run only the specified aspect(s). Repeatable. "
            f"Valid: {', '.join(ASPECTS_V1)}"
        ),
    )
    aspect_sel.add_argument(
        "--preset",
        default=None,
        type=parse_preset_name,
        metavar="NAME",
        help=(
            "Run a builtin preset (expands to multiple aspects). "
            f"Builtins: {', '.join(sorted(BUILTIN_PRESETS.keys()))}"
        ),
    )

    review.add_argument(
        "--full",
        action="store_true",
        help="Disable incremental diff and force full PR diff review",
    )
    review.add_argument(
        "--no-sot-aspect",
        action="append",
        default=[],
        type=parse_aspect,
        metavar="NAME",
        help=(
            "Disable SoT injection for the specified aspect (repeatable). "
            f"Valid: {', '.join(ASPECTS_V1)}"
        ),
    )

    review.add_argument(
        "--post",
        action="store_true",
        help="Post/update the summary comment on the PR",
    )
    review.add_argument(
        "--inline",
        action="store_true",
        help="Post/update inline review comments for P0/P1 findings",
    )
    review.add_argument(
        "--hybrid-aspect",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Allow repo read-only access for this aspect (repeatable). "
            "Requires --hybrid-allowlist."
        ),
    )
    review.add_argument(
        "--hybrid-allowlist",
        action="append",
        default=[],
        metavar="GLOB",
        help="Repo read-only allowlist path glob (repeatable)",
    )
    review.add_argument(
        "--explore",
        action="store_true",
        help="Enable OpenCode explore mode (tool trace + policy gating)",
    )
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


def _state_json_path(out_dir: str) -> str:
    return os.path.join(out_dir, "state.json")


def _load_state_json(out_dir: str) -> dict[str, Any]:
    path = _state_json_path(out_dir)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _write_state_json(
    out_dir: str,
    *,
    repo: str,
    pr: int,
    head_sha: str,
    incremental_base_head_sha: str,
    selected_aspects: tuple[str, ...],
    no_sot_aspects: tuple[str, ...],
) -> str:
    path = _state_json_path(out_dir)
    payload = {
        "schema_version": 1,
        "updated_at": now_utc_z(),
        "repo": repo,
        "pr": pr,
        "head_sha": head_sha,
        "incremental_base_head_sha": incremental_base_head_sha,
        "selected_aspects": list(selected_aspects),
        "no_sot_aspects": list(no_sot_aspects),
    }
    atomic_write_json_secure(path, payload)
    return path


def clear_stale_review_summary(out_dir: str) -> None:
    for name in ("review-summary.json", "review-summary.md"):
        try:
            os.remove(os.path.join(out_dir, name))
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _should_clear_stale_summary_on_post_failure(exc: ExecFailureError) -> bool:
    message = str(exc).lower()
    return (
        "pr head changed; skip stale summary mutation" in message
        or "pr head changed; skip stale inline mutation" in message
    )


def _raise_invalid_review_args(message: str) -> None:
    full = f"killer-7 review: error: {message}\n"
    sys.stderr.write(full)
    raise ParserExit(2, full)


def handle_review(args: argparse.Namespace) -> dict[str, Any]:
    selected_aspects: tuple[str, ...] = ASPECTS_V1
    preset = (args.preset or "").strip() if hasattr(args, "preset") else ""
    raw_aspects = list(args.aspect or []) if hasattr(args, "aspect") else []
    if preset:
        selected_aspects = resolve_preset(preset)
    elif raw_aspects:
        seen: set[str] = set()
        for a in raw_aspects:
            if a in seen:
                _raise_invalid_review_args(f"Duplicate aspect: {a!r}")
            seen.add(a)
        selected_aspects = tuple(raw_aspects)

    requested_no_sot = (
        tuple(args.no_sot_aspect or []) if hasattr(args, "no_sot_aspect") else ()
    )
    no_sot_aspects = set(DEFAULT_NO_SOT_ASPECTS)
    no_sot_aspects.update(requested_no_sot)
    no_sot_aspects.intersection_update(set(selected_aspects))

    # Fetch PR input (diff + metadata) and write artifacts.
    out_dir = ensure_artifacts_dir(os.getcwd())

    state_payload = _load_state_json(out_dir)
    prev_repo = state_payload.get("repo")
    prev_pr = state_payload.get("pr")
    has_prev_incremental_base = "incremental_base_head_sha" in state_payload
    prev_head = state_payload.get("head_sha")
    prev_incremental_base_head = state_payload.get("incremental_base_head_sha")
    prev_selected_aspects = state_payload.get("selected_aspects")
    prev_no_sot_aspects = state_payload.get("no_sot_aspects")
    prev_no_sot_aspects_list: list[object] | None
    if prev_no_sot_aspects is None:
        prev_no_sot_aspects_list = []
    elif isinstance(prev_no_sot_aspects, list):
        prev_no_sot_aspects_list = prev_no_sot_aspects
    else:
        prev_no_sot_aspects_list = None

    incremental_requested = not bool(getattr(args, "full", False))
    incremental_applied = False
    incremental_reason = ""
    incremental_base_head_sha = ""

    prev_head_for_incremental: str | None
    if (
        isinstance(prev_incremental_base_head, str)
        and prev_incremental_base_head.strip()
    ):
        prev_head_for_incremental = prev_incremental_base_head
    elif has_prev_incremental_base:
        prev_head_for_incremental = None
    elif isinstance(prev_head, str) and prev_head.strip():
        prev_head_for_incremental = prev_head
    else:
        prev_head_for_incremental = None

    if not incremental_requested:
        incremental_reason = "forced_full"
    elif (
        not isinstance(prev_head_for_incremental, str)
        or not prev_head_for_incremental.strip()
    ):
        incremental_reason = "missing_previous_head"
    elif prev_repo != args.repo or prev_pr != args.pr:
        incremental_reason = "previous_scope_mismatch"
    elif not isinstance(prev_selected_aspects, list) or not prev_selected_aspects:
        incremental_reason = "missing_previous_selected_aspects"
    elif any(not isinstance(a, str) or not a.strip() for a in prev_selected_aspects):
        incremental_reason = "invalid_previous_selected_aspects"
    elif set(prev_selected_aspects) != set(selected_aspects):
        incremental_reason = "previous_aspects_mismatch"
    elif prev_no_sot_aspects_list is None:
        incremental_reason = "invalid_previous_no_sot_aspects"
    elif any(not isinstance(a, str) or not a.strip() for a in prev_no_sot_aspects_list):
        incremental_reason = "invalid_previous_no_sot_aspects"
    elif set(prev_no_sot_aspects_list) != set(no_sot_aspects):
        incremental_reason = "previous_no_sot_aspects_mismatch"
    else:
        base_head = prev_head_for_incremental.strip()
        incremental_base_head_sha = base_head
        incremental_applied = True
        incremental_reason = "head_based_incremental"

    try:
        if incremental_applied:
            try:
                pr_input = fetch_pr_input(
                    repo=args.repo,
                    pr=args.pr,
                    base_head_sha=incremental_base_head_sha,
                )
            except ExecFailureError as exc:
                if "PR head changed during input fetch" in str(exc):
                    clear_stale_review_summary(out_dir)
                    raise
                incremental_applied = False
                incremental_reason = f"incremental_fallback_full: {exc}"
                pr_input = fetch_pr_input(repo=args.repo, pr=args.pr)
        else:
            pr_input = fetch_pr_input(repo=args.repo, pr=args.pr)

        if pr_input.diff_mode != "incremental":
            incremental_applied = False
            if incremental_reason == "head_based_incremental":
                incremental_reason = "same_head_full_diff"
            elif not incremental_reason:
                incremental_reason = "full_diff"
    except ExecFailureError:
        clear_stale_review_summary(out_dir)
        raise
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
        out: list[str] = []
        for ch in s:
            cat = unicodedata.category(ch)
            if cat in {"Cc", "Cf"} or (not ch.isprintable()):
                o = ord(ch)
                if o <= 0xFF:
                    out.append(f"\\x{o:02x}")
                elif o <= 0xFFFF:
                    out.append(f"\\u{o:04x}")
                else:
                    out.append(f"\\U{o:08x}")
                continue
            out.append(ch)
        return "".join(out)

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

    tool_bundle_files: list[str] = []
    tool_bundle_index: dict[str, set[int]] = {}

    def scan_tool_bundle() -> tuple[list[str], dict[str, set[int]], list[str]]:
        tool_bundle_dir = os.path.join(out_dir, "tool-bundle")
        if os.path.exists(tool_bundle_dir) and (not os.path.isdir(tool_bundle_dir)):
            initial_warning_lines: list[str] = [
                "tool_bundle_dir_skipped kind=not_a_directory"
                f" path={one_line(os.path.relpath(tool_bundle_dir, os.getcwd()))}"
            ]
            return ([], {}, initial_warning_lines)
        if not os.path.isdir(tool_bundle_dir):
            return ([], {}, [])

        extra_warning_lines: list[str] = []
        tool_bundle_files: list[str] = []
        tool_bundle_index: dict[str, set[int]] = {}

        out_dir_real = os.path.realpath(out_dir)
        if os.path.islink(tool_bundle_dir):
            extra_warning_lines.append(
                "tool_bundle_dir_skipped kind=is_symlink"
                f" path={one_line(os.path.relpath(tool_bundle_dir, os.getcwd()))}"
            )
            return ([], {}, extra_warning_lines)
        tool_bundle_dir_real = os.path.realpath(tool_bundle_dir)
        try:
            under_artifacts = (
                os.path.commonpath([out_dir_real, tool_bundle_dir_real]) == out_dir_real
            )
        except ValueError:
            under_artifacts = False
        if not under_artifacts:
            extra_warning_lines.append(
                "tool_bundle_dir_skipped kind=escapes_artifacts"
                f" path={one_line(os.path.relpath(tool_bundle_dir, os.getcwd()))}"
            )
            return ([], {}, extra_warning_lines)

        max_bytes = 100 * 1024
        manifest_path = os.path.join(tool_bundle_dir, "manifest.json")
        manifest: dict[str, object] = {}
        if not os.path.isfile(manifest_path):
            manifest_present = False
            extra_warning_lines.append(
                "tool_bundle_manifest_skipped kind=missing"
                f" path={one_line(os.path.relpath(manifest_path, os.getcwd()))}"
            )
        elif os.path.islink(manifest_path):
            manifest_present = False
            extra_warning_lines.append(
                "tool_bundle_manifest_skipped kind=is_symlink"
                f" path={one_line(os.path.relpath(manifest_path, os.getcwd()))}"
            )
        else:
            manifest_present = True

        if manifest_present:
            max_manifest_bytes = 64 * 1024
            try:
                manifest_size_bytes = os.path.getsize(manifest_path)
            except OSError as exc:
                extra_warning_lines.append(
                    "tool_bundle_manifest_skipped kind=stat_failed"
                    f" path={one_line(os.path.relpath(manifest_path, os.getcwd()))}"
                    f" message={one_line(str(exc))}"
                )
                manifest_present = False
            else:
                if manifest_size_bytes > max_manifest_bytes:
                    extra_warning_lines.append(
                        "tool_bundle_manifest_skipped kind=size_limit_exceeded"
                        f" path={one_line(os.path.relpath(manifest_path, os.getcwd()))}"
                        f" size_bytes={manifest_size_bytes}"
                        f" limit_bytes={max_manifest_bytes}"
                    )
                    manifest_present = False

        if manifest_present:
            try:
                with open(manifest_path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict):
                    manifest = loaded
                else:
                    extra_warning_lines.append(
                        "tool_bundle_manifest_skipped kind=invalid_type"
                        f" path={one_line(os.path.relpath(manifest_path, os.getcwd()))}"
                    )
                    manifest_present = False
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                extra_warning_lines.append(
                    "tool_bundle_manifest_skipped kind=invalid_json"
                    f" path={one_line(os.path.relpath(manifest_path, os.getcwd()))}"
                    f" message={one_line(str(exc))}"
                )
                manifest_present = False

        head_obj = manifest.get("head_sha")
        head_sha = head_obj if isinstance(head_obj, str) else ""
        if not head_sha:
            if manifest_present:
                extra_warning_lines.append(
                    "tool_bundle_manifest_skipped kind=missing_head_sha"
                    f" path={one_line(os.path.relpath(manifest_path, os.getcwd()))}"
                )
            names: list[str] = []
        elif head_sha != pr_input.head_sha:
            extra_warning_lines.append(
                "tool_bundle_manifest_skipped kind=head_sha_mismatch"
                f" expected={one_line(pr_input.head_sha)}"
                f" actual={one_line(head_sha)}"
            )
            names = []
        else:
            files_obj = manifest.get("files")
            if not isinstance(files_obj, list):
                extra_warning_lines.append(
                    "tool_bundle_manifest_skipped kind=invalid_files"
                    f" path={one_line(os.path.relpath(manifest_path, os.getcwd()))}"
                )
                names = []
            else:
                names = []
                max_manifest_entries = 1000
                if len(files_obj) > max_manifest_entries:
                    extra_warning_lines.append(
                        "tool_bundle_manifest_files_truncated"
                        f" total={len(files_obj)}"
                        f" limit={max_manifest_entries}"
                    )
                for raw in files_obj[:max_manifest_entries]:
                    if not isinstance(raw, str):
                        continue
                    n = raw.strip()
                    if not n:
                        continue
                    if "/" in n or "\\" in n:
                        continue
                    if n in {".", ".."}:
                        continue
                    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.txt", n):
                        continue
                    names.append(n)

        max_files = 200
        max_total_bytes = 1 * 1024 * 1024
        seen_names: set[str] = set()
        processed_files = 0
        processed_total_bytes = 0

        for name in names:
            if not name.endswith(".txt"):
                continue
            if name in seen_names:
                continue
            seen_names.add(name)

            if processed_files >= max_files:
                extra_warning_lines.append(
                    "tool_bundle_processing_stopped kind=max_files_exceeded"
                    f" max_files={max_files}"
                )
                break

            processed_files += 1

            p = os.path.join(tool_bundle_dir, name)
            if os.path.islink(p):
                extra_warning_lines.append(
                    "tool_bundle_file_skipped kind=is_symlink"
                    f" path={one_line(os.path.relpath(p, os.getcwd()))}"
                )
                continue
            p_real = os.path.realpath(p)
            try:
                under_tool_bundle = (
                    os.path.commonpath([tool_bundle_dir_real, p_real])
                    == tool_bundle_dir_real
                )
            except ValueError:
                under_tool_bundle = False
            if not under_tool_bundle:
                extra_warning_lines.append(
                    "tool_bundle_file_skipped kind=escapes_tool_bundle"
                    f" path={one_line(os.path.relpath(p, os.getcwd()))}"
                )
                continue
            if not os.path.isfile(p):
                extra_warning_lines.append(
                    "tool_bundle_file_skipped kind=missing"
                    f" path={one_line(os.path.relpath(p, os.getcwd()))}"
                )
                continue
            try:
                size_bytes = os.path.getsize(p)
            except OSError as exc:
                extra_warning_lines.append(
                    "tool_bundle_file_skipped kind=stat_failed"
                    f" path={one_line(os.path.relpath(p, os.getcwd()))}"
                    f" message={one_line(str(exc))}"
                )
                continue

            if size_bytes > max_bytes:
                extra_warning_lines.append(
                    "tool_bundle_file_skipped kind=size_limit_exceeded"
                    f" path={one_line(os.path.relpath(p, os.getcwd()))}"
                    f" size_bytes={size_bytes}"
                    f" limit_bytes={max_bytes}"
                )
                continue

            if processed_total_bytes + size_bytes > max_total_bytes:
                extra_warning_lines.append(
                    "tool_bundle_processing_stopped kind=max_total_bytes_exceeded"
                    f" max_total_bytes={max_total_bytes}"
                    f" next_file_size_bytes={size_bytes}"
                )
                break

            processed_total_bytes += size_bytes

            try:
                with open(p, "rb") as fh:
                    raw = fh.read(max_bytes + 1)
            except OSError as exc:
                extra_warning_lines.append(
                    "tool_bundle_file_skipped kind=read_failed"
                    f" path={one_line(os.path.relpath(p, os.getcwd()))}"
                    f" message={one_line(str(exc))}"
                )
                continue

            if len(raw) > max_bytes:
                extra_warning_lines.append(
                    "tool_bundle_file_skipped kind=size_limit_exceeded"
                    f" path={one_line(os.path.relpath(p, os.getcwd()))}"
                    f" size_bytes={len(raw)}"
                    f" limit_bytes={max_bytes}"
                )
                continue

            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                extra_warning_lines.append(
                    "tool_bundle_file_skipped kind=decode_error"
                    f" path={one_line(os.path.relpath(p, os.getcwd()))}"
                    f" size_bytes={size_bytes}"
                )
                continue

            extra_index = parse_context_bundle_index(text)
            for src_path, lines in extra_index.items():
                normalized = _normalize_tool_bundle_src_path(src_path)
                if not normalized:
                    extra_warning_lines.append(
                        "tool_bundle_src_skipped kind=invalid_src"
                        f" path={one_line(os.path.relpath(p, os.getcwd()))}"
                    )
                    continue

                aliases = {normalized, f"./{normalized}"}
                if os.sep == "\\":
                    back = normalized.replace("/", "\\")
                    aliases.add(back)
                    aliases.add(f".\\{back}")
                for key in sorted(aliases):
                    if key in tool_bundle_index:
                        tool_bundle_index[key].update(lines)
                    else:
                        tool_bundle_index[key] = set(lines)

            tool_bundle_files.append(
                os.path.relpath(p, os.getcwd()).replace(os.sep, "/")
            )

        return (tool_bundle_files, tool_bundle_index, extra_warning_lines)

    warnings_txt_path = write_warnings_txt(out_dir, warning_lines)
    # Run all review aspects (Issue #8) in parallel and write aspect artifacts.
    # Keep scope_id deterministic and tied to the PR input.
    scope_id = f"{args.repo}#pr-{args.pr}@{pr_input.head_sha[:12]}"
    try:
        hybrid_policy = build_hybrid_policy(
            hybrid_aspects=list(args.hybrid_aspect or []),
            hybrid_allowlist=list(args.hybrid_allowlist or []),
        )
    except ExecFailureError:
        clear_stale_review_summary(out_dir)
        raise

    def runner_env_for_aspect(aspect: str) -> dict[str, str]:
        base_env = hybrid_policy.decision_for(aspect=aspect).runner_env()
        if not args.explore:
            return base_env
        out = dict(base_env)
        out["KILLER7_EXPLORE"] = "1"
        return out

    if args.explore:
        for aspect in selected_aspects:
            aspect_dir = opencode_artifacts_dir(out_dir, aspect)
            for name in ("tool-trace.jsonl", "tool-bundle.txt", "stdout.jsonl"):
                p = os.path.join(aspect_dir, name)
                if not os.path.exists(p):
                    continue
                try:
                    os.remove(p)
                except OSError as exc:
                    raise ExecFailureError(
                        f"Failed to remove stale explore artifact: {p}: {type(exc).__name__}: {exc}"
                    ) from exc

    deferred_exc: BlockedError | ExecFailureError | None = None
    aspects_result: dict[str, object]
    try:
        aspects_result = run_all_aspects(
            base_dir=os.getcwd(),
            scope_id=scope_id,
            context_bundle=diff_bundle,
            sot=sot_md,
            aspects=selected_aspects,
            max_llm_calls=8,
            max_workers=8,
            runner_env_for_aspect=runner_env_for_aspect,
            sot_for_aspect=(lambda aspect: "" if aspect in no_sot_aspects else sot_md),
        )
    except (BlockedError, ExecFailureError) as exc:
        # Even when some aspects fail/block, `.ai-review/aspects/index.json` is written.
        # Continue to generate evidence/policy artifacts to aid debugging, then re-raise.
        deferred_exc = exc

        if isinstance(exc, ExecFailureError):
            # Avoid leaving stale `review-summary.*` from a previous successful run.
            clear_stale_review_summary(out_dir)

        aspects_result = {
            "scope_id": scope_id,
            "index_path": os.path.join(out_dir, "aspects", "index.json"),
        }

    tool_trace_txt = ""
    tool_bundle_txt = ""
    if args.explore:

        def _join_capped(chunks: list[str], *, max_bytes: int) -> str:
            if max_bytes < 1:
                return ""
            buf = bytearray()
            first = True
            truncated = False

            for raw in chunks:
                s = (raw or "").rstrip("\n")
                if not s.strip():
                    continue
                if not first:
                    s = "\n" + s
                b = s.encode("utf-8")
                if len(buf) + len(b) > max_bytes:
                    remaining = max_bytes - len(buf)
                    if remaining > 0:
                        buf.extend(b[:remaining])
                    truncated = True
                    break
                buf.extend(b)
                first = False

            if not buf:
                return ""
            if truncated:
                last_nl = buf.rfind(b"\n")
                if last_nl >= 0:
                    buf = buf[:last_nl]
            return buf.decode("utf-8", errors="replace").rstrip("\n")

        trace_chunks: list[str] = []
        bundle_chunks: list[str] = []
        for aspect in selected_aspects:
            aspect_dir = opencode_artifacts_dir(out_dir, aspect)

            p_trace = os.path.join(aspect_dir, "tool-trace.jsonl")
            p_bundle = os.path.join(aspect_dir, "tool-bundle.txt")
            if os.path.isfile(p_trace):
                try:
                    with open(p_trace, "r", encoding="utf-8", errors="replace") as fh:
                        trace_chunks.append(fh.read() or "")
                except OSError:
                    raise ExecFailureError(
                        f"Failed to read explore tool trace: {p_trace}"
                    )
            if os.path.isfile(p_bundle):
                try:
                    with open(p_bundle, "r", encoding="utf-8", errors="replace") as fh:
                        bundle_chunks.append(fh.read() or "")
                except OSError:
                    raise ExecFailureError(
                        f"Failed to read explore tool bundle: {p_bundle}"
                    )

        max_trace_bytes = 1_000_000
        tool_trace_txt = _join_capped(trace_chunks, max_bytes=max_trace_bytes)
        max_bundle_bytes = 300_000
        raw = (os.environ.get("KILLER7_EXPLORE_MAX_BUNDLE_BYTES") or "").strip()
        if raw:
            try:
                max_bundle_bytes = int(raw)
            except ValueError:
                max_bundle_bytes = 300_000
        tool_bundle_txt = _join_capped(bundle_chunks, max_bytes=max_bundle_bytes)

        # `scan_tool_bundle()` only ingests files up to 100KiB.
        scan_bundle_max_bytes = 100 * 1024
        tool_bundle_txt_for_scan = _join_capped(
            [tool_bundle_txt], max_bytes=scan_bundle_max_bytes
        )

        _ = write_tool_trace_jsonl(out_dir, tool_trace_txt)
        _ = write_tool_bundle_txt(out_dir, tool_bundle_txt)

        tool_bundle_dir = os.path.join(out_dir, "tool-bundle")
        try:
            os.makedirs(tool_bundle_dir, mode=0o700, exist_ok=True)
        except OSError as exc:
            raise ExecFailureError(
                f"Failed to create tool bundle dir: {tool_bundle_dir}: {type(exc).__name__}: {exc}"
            ) from exc

        explore_bundle_name = "explore.txt"
        explore_bundle_path = os.path.join(tool_bundle_dir, explore_bundle_name)
        atomic_write_text_secure(explore_bundle_path, tool_bundle_txt_for_scan)
        atomic_write_json_secure(
            os.path.join(tool_bundle_dir, "manifest.json"),
            {
                "schema_version": 1,
                "head_sha": pr_input.head_sha,
                "files": [explore_bundle_name],
            },
        )

    # Evidence validation + policy application (Issue #10)
    tool_bundle_files, tool_bundle_index, tool_bundle_warning_lines = scan_tool_bundle()
    if tool_bundle_warning_lines:
        warning_lines.extend(tool_bundle_warning_lines)
        warnings_txt_path = write_warnings_txt(out_dir, warning_lines)

    context_index = parse_context_bundle_index(context_bundle_txt)

    for src_path, lines in tool_bundle_index.items():
        if src_path in context_index:
            context_index[src_path].update(lines)
        else:
            context_index[src_path] = set(lines)

    def require_int(v: object, *, key: str, aspect: str) -> int:
        if type(v) is not int:
            raise ExecFailureError(
                f"Invalid evidence stats: {aspect}.{key} must be int"
            )
        return v

    index_path = str(aspects_result.get("index_path", ""))
    per_aspect: dict[str, object] = {}
    summary_reviews: dict[str, dict[str, object]] = {}
    evidence_index_aspects: list[dict[str, object]] = []
    policy_index_aspects: list[dict[str, object]] = []
    totals = {
        "aspects_total": 0,
        "aspects_ok": 0,
        "aspects_failed": 0,
        "total_in": 0,
        "total_out": 0,
        "excluded_count": 0,
        "downgraded_count": 0,
        "verified_true_count": 0,
        "verified_false_count": 0,
    }

    if not index_path:
        raise ExecFailureError("Missing aspects index_path")

    if deferred_exc is not None and not os.path.isfile(index_path):
        # Some input/config failures can occur before `index.json` is written.
        # Preserve the original error in that case.
        raise deferred_exc
    if not os.path.isfile(index_path):
        raise ExecFailureError("Missing aspects index.json artifact")

    out_dir_real = os.path.realpath(out_dir)
    index_path_real = os.path.realpath(index_path)
    if not (
        index_path_real == out_dir_real
        or index_path_real.startswith(out_dir_real + os.sep)
    ):
        raise ExecFailureError(
            "Invalid aspects index_path: must stay within artifacts dir"
        )

    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            index_payload = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        raise ExecFailureError(f"Failed to read aspects index JSON: {exc}") from exc

    if not isinstance(index_payload, dict):
        raise ExecFailureError("Invalid aspects index JSON: root must be object")

    aspects_list = index_payload.get("aspects")
    if not isinstance(aspects_list, list):
        raise ExecFailureError("Invalid aspects index JSON: 'aspects' must be an array")

    for i, entry in enumerate(aspects_list):
        totals["aspects_total"] += 1
        if not isinstance(entry, dict):
            raise ExecFailureError(
                f"Invalid aspects index JSON: aspects[{i}] must be an object"
            )

        aspect_name = entry.get("aspect")
        ok = entry.get("ok")
        rel_path = entry.get("result_path")

        if not isinstance(aspect_name, str) or not aspect_name:
            raise ExecFailureError(
                f"Invalid aspects index JSON: aspects[{i}].aspect must be a non-empty string"
            )
        if not isinstance(ok, bool):
            raise ExecFailureError(
                f"Invalid aspects index JSON: aspects[{i}].ok must be boolean"
            )
        if ok is not True:
            totals["aspects_failed"] += 1
            aspect_info: dict[str, object] = {
                "ok": False,
            }

            raw_input = rel_path if isinstance(rel_path, str) else ""
            raw_input = raw_input.replace("\\", "/")
            result_path = ""
            if raw_input:
                # Even on failure, avoid writing paths that escape the artifacts dir.
                candidate = os.path.join(out_dir, raw_input)
                candidate_real = os.path.realpath(candidate)
                if candidate_real == out_dir_real or candidate_real.startswith(
                    out_dir_real + os.sep
                ):
                    result_path = raw_input

            error_kind = entry.get("error_kind")
            error_message = entry.get("error_message")
            if isinstance(error_kind, str) and error_kind:
                aspect_info["error_kind"] = error_kind
            if isinstance(error_message, str) and error_message:
                aspect_info["error_message"] = error_message
            if result_path:
                aspect_info["result_path"] = result_path

            per_aspect[aspect_name] = aspect_info

            evidence_index_aspects.append(
                {
                    "aspect": aspect_name,
                    "ok": False,
                    "result_path": result_path,
                    "evidence_path": "",
                }
            )
            policy_index_aspects.append(
                {
                    "aspect": aspect_name,
                    "ok": False,
                    "result_path": result_path,
                    "policy_path": "",
                }
            )
            continue
        if not isinstance(rel_path, str) or not rel_path:
            raise ExecFailureError(
                f"Invalid aspects index JSON: ok=true but result_path missing for aspect={aspect_name!r}"
            )

        totals["aspects_ok"] += 1

        # Guard against path traversal in index.json.
        out_dir_real = os.path.realpath(out_dir)
        src_path = os.path.join(out_dir, rel_path)
        src_path_real = os.path.realpath(src_path)
        if not (
            src_path_real == out_dir_real
            or src_path_real.startswith(out_dir_real + os.sep)
        ):
            raise ExecFailureError(
                f"Invalid aspect result_path: must stay within artifacts dir: {rel_path!r}"
            )
        try:
            with open(src_path, "r", encoding="utf-8") as fh:
                review_payload = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            raise ExecFailureError(
                f"Failed to read aspect JSON: {src_path}: {exc}"
            ) from exc

        if not isinstance(review_payload, dict):
            raise ExecFailureError(f"Aspect JSON must be an object: {src_path}")

        findings = review_payload.get("findings")
        if not isinstance(findings, list):
            raise ExecFailureError(f"Aspect JSON findings must be an array: {src_path}")
        if any(not isinstance(x, dict) for x in findings):
            raise ExecFailureError(
                f"Aspect JSON findings entries must be objects: {src_path}"
            )
        questions = review_payload.get("questions")
        if not isinstance(questions, list):
            raise ExecFailureError(
                f"Aspect JSON questions must be an array: {src_path}"
            )

        out_findings, stats = apply_evidence_policy_to_findings(findings, context_index)

        updated_review = dict(review_payload)
        updated_review["findings"] = out_findings
        updated_review["status"] = recompute_review_status(out_findings, questions)

        policy_review = dict(review_payload)
        policy_findings = _strip_machine_fields_from_findings(out_findings)
        policy_review["findings"] = policy_findings
        policy_review["status"] = recompute_review_status(policy_findings, questions)

        # Preserve the raw (pre-policy) review for debugging/auditing.
        raw_path = f"{os.path.splitext(src_path)[0]}.raw.json"
        atomic_write_json_secure(raw_path, review_payload)

        raw_rel_path = os.path.relpath(raw_path, out_dir).replace(os.sep, "/")
        canonical_rel_path = rel_path.replace(os.sep, "/")

        # Make the policy-applied review canonical for any downstream consumers
        # that still read `.ai-review/aspects/<aspect>.json`.
        atomic_write_json_secure(src_path, policy_review)

        aspect_evidence_payload = {
            "schema_version": 1,
            "kind": "aspect_evidence",
            "generated_at": now_utc_z(),
            "scope_id": scope_id,
            "aspect": aspect_name,
            "input_path": raw_rel_path,
            "canonical_path": canonical_rel_path,
            "review": updated_review,
            "stats": stats,
        }

        evidence_path = write_aspect_evidence_json(
            out_dir, aspect=aspect_name, payload=aspect_evidence_payload
        )

        policy_path = write_aspect_policy_json(
            out_dir, aspect=aspect_name, payload=policy_review
        )

        # Use the evidence/policy-applied review with machine fields preserved for
        # aggregated report generation (review-summary.json).
        summary_reviews[aspect_name] = dict(updated_review)

        per_aspect[aspect_name] = {
            "ok": True,
            "input_path": raw_rel_path,
            "canonical_path": canonical_rel_path,
            "evidence_path": os.path.relpath(evidence_path, out_dir).replace(
                os.sep, "/"
            ),
            "policy_path": os.path.relpath(policy_path, out_dir).replace(os.sep, "/"),
            "stats": stats,
        }

        evidence_index_aspects.append(
            {
                "aspect": aspect_name,
                "ok": True,
                "result_path": canonical_rel_path,
                "input_path": raw_rel_path,
                "evidence_path": os.path.relpath(evidence_path, out_dir).replace(
                    os.sep, "/"
                ),
            }
        )
        policy_index_aspects.append(
            {
                "aspect": aspect_name,
                "ok": True,
                "result_path": rel_path.replace(os.sep, "/"),
                "policy_path": os.path.relpath(policy_path, out_dir).replace(
                    os.sep, "/"
                ),
            }
        )

        if not isinstance(stats, dict):
            raise ExecFailureError(
                f"Invalid evidence stats: {aspect_name}.stats must be an object"
            )

        total_in = require_int(
            stats.get("total_in"), key="total_in", aspect=aspect_name
        )
        total_out = require_int(
            stats.get("total_out"), key="total_out", aspect=aspect_name
        )
        excluded_count = require_int(
            stats.get("excluded_count"), key="excluded_count", aspect=aspect_name
        )
        downgraded_count = require_int(
            stats.get("downgraded_count"), key="downgraded_count", aspect=aspect_name
        )
        verified_true_count = require_int(
            stats.get("verified_true_count"),
            key="verified_true_count",
            aspect=aspect_name,
        )
        if verified_true_count > total_in:
            raise ExecFailureError(
                f"Invalid evidence stats: {aspect_name}.verified_true_count must be <= total_in"
            )

        totals["total_in"] += total_in
        totals["total_out"] += total_out
        totals["excluded_count"] += excluded_count
        totals["downgraded_count"] += downgraded_count
        totals["verified_true_count"] += verified_true_count
        totals["verified_false_count"] += total_in - verified_true_count

    evidence_payload = {
        "schema_version": 1,
        "kind": "evidence_summary",
        "generated_at": now_utc_z(),
        "scope_id": scope_id,
        "policy": EVIDENCE_POLICY_V1,
        "totals": totals,
        "per_aspect": per_aspect,
    }

    evidence_json_path = write_evidence_json(out_dir, evidence_payload)

    evidence_index_path = write_aspects_evidence_index_json(
        out_dir,
        {
            "schema_version": 1,
            "kind": "aspects_evidence_index",
            "generated_at": now_utc_z(),
            "scope_id": scope_id,
            "aspects": evidence_index_aspects,
        },
    )
    policy_index_path = write_aspects_policy_index_json(
        out_dir,
        {
            "schema_version": 1,
            "kind": "aspects_policy_index",
            "generated_at": now_utc_z(),
            "scope_id": scope_id,
            "aspects": policy_index_aspects,
        },
    )

    summary_json_path = ""
    summary_md_path = ""
    summary_payload: dict[str, object] | None = None
    rerun_plan_path = ""
    post_result: dict[str, object] = {}
    inline_result: dict[str, object] = {}
    if deferred_exc is None or isinstance(deferred_exc, BlockedError):
        summary_payload = merge_review_summary(
            scope_id=scope_id, aspect_reviews=summary_reviews
        )

        if isinstance(deferred_exc, BlockedError):
            # If aspect execution is blocked (e.g., missing binaries/auth), do not emit an
            # "Approved" review-summary just because no findings/questions exist.
            summary_payload["status"] = "Blocked"
            msg = str(deferred_exc).strip()
            if msg:
                summary_payload["overall_explanation"] = msg

            # Best-effort: mark failed aspects as Blocked for easier debugging.
            statuses_obj = summary_payload.get("aspect_statuses")
            merged_statuses: dict[str, str] = (
                dict(statuses_obj) if isinstance(statuses_obj, dict) else {}
            )
            for entry in aspects_list:
                if not isinstance(entry, dict):
                    continue
                a = entry.get("aspect")
                ok = entry.get("ok")
                if isinstance(a, str) and a and ok is not True:
                    merged_statuses[a] = "Blocked"
            if merged_statuses:
                summary_payload["aspect_statuses"] = merged_statuses

        validate_review_summary_json(summary_payload, expected_scope_id=scope_id)
        summary_json_path = write_review_summary_json(out_dir, summary_payload)
        summary_md_path = write_review_summary_md(
            out_dir, format_review_summary_md(summary_payload)
        )
        summary_status = summary_payload.get("status")

        question_aspects: list[str] = []
        for aspect, review in summary_reviews.items():
            qs_obj = review.get("questions")
            if isinstance(qs_obj, list) and any(
                isinstance(x, str) and x.strip() for x in qs_obj
            ):
                question_aspects.append(aspect)
        rerun_aspects = [
            a
            for a in question_aspects
            if hybrid_policy.decision_for(aspect=a).repo_read_only
        ]
        if rerun_aspects:
            rerun = write_questions_rerun_artifacts(
                out_dir=out_dir,
                repo=args.repo,
                pr=args.pr,
                head_sha=pr_input.head_sha,
                question_aspects=rerun_aspects,
                hybrid_allowlist=list(hybrid_policy.allowlist_paths),
            )
            rerun_plan_path = str(rerun.get("plan_path") or "")

        if summary_status == "Blocked" and deferred_exc is None:
            deferred_exc = BlockedError(
                f"Review is blocked. See: {os.path.relpath(summary_json_path, os.getcwd())}"
            )

    should_post_summary = bool(args.post or args.inline)
    if should_post_summary and summary_payload is not None:
        gh_client = GhClient.from_env()
        try:
            current_head_sha = gh_client.pr_head_ref_oid(repo=args.repo, pr=args.pr)
            if current_head_sha != pr_input.head_sha:
                clear_stale_review_summary(out_dir)
                summary_json_path = ""
                summary_md_path = ""
                post_result = {
                    "mode": "skipped_stale_head",
                    "expected_head_sha": pr_input.head_sha,
                    "current_head_sha": current_head_sha,
                }
                deferred_exc = ExecFailureError(
                    "PR head changed before summary posting; rerun review on latest head"
                )
            else:
                post_result = post_summary_comment(
                    repo=args.repo,
                    pr=args.pr,
                    head_sha=pr_input.head_sha,
                    expected_head_sha=pr_input.head_sha,
                    summary=summary_payload,
                )
                latest_head_sha = gh_client.pr_head_ref_oid(repo=args.repo, pr=args.pr)
                if latest_head_sha != pr_input.head_sha:
                    clear_stale_review_summary(out_dir)
                    post_result = {
                        "mode": "stale_head_after_post",
                        "expected_head_sha": pr_input.head_sha,
                        "current_head_sha": latest_head_sha,
                    }
                    deferred_exc = ExecFailureError(
                        "PR head changed during summary posting; rerun review on latest head"
                    )

                if args.inline and (
                    deferred_exc is None or isinstance(deferred_exc, BlockedError)
                ):
                    inline_diff_patch = pr_input.diff_patch
                    if pr_input.diff_mode == "incremental":
                        inline_diff_patch = gh_client.pr_diff_patch(
                            repo=args.repo, pr=args.pr
                        )
                    inline_result = post_inline_comments(
                        repo=args.repo,
                        pr=args.pr,
                        head_sha=pr_input.head_sha,
                        expected_head_sha=pr_input.head_sha,
                        review_summary=summary_payload,
                        diff_patch=inline_diff_patch,
                    )
                    try:
                        raise_if_inline_blocked(inline_result)
                    except BlockedError as exc:
                        deferred_exc = exc
        except ExecFailureError as exc:
            if _should_clear_stale_summary_on_post_failure(exc):
                clear_stale_review_summary(out_dir)
            raise

    next_incremental_base = pr_input.head_sha
    if deferred_exc is not None:
        if (
            isinstance(prev_head_for_incremental, str)
            and prev_repo == args.repo
            and prev_pr == args.pr
        ):
            next_incremental_base = prev_head_for_incremental.strip()
        else:
            next_incremental_base = ""

    state_json_path = _write_state_json(
        out_dir,
        repo=args.repo,
        pr=args.pr,
        head_sha=pr_input.head_sha,
        incremental_base_head_sha=next_incremental_base,
        selected_aspects=selected_aspects,
        no_sot_aspects=tuple(sorted(no_sot_aspects)),
    )

    if deferred_exc is not None:
        raise deferred_exc

    return {
        "action": "review",
        "repo": args.repo,
        "pr": args.pr,
        "head_sha": pr_input.head_sha,
        "scope_id": scope_id,
        "selected_aspects": list(selected_aspects),
        "incremental": {
            "requested": incremental_requested,
            "applied": incremental_applied,
            "reason": incremental_reason,
            "base_head_sha": pr_input.base_head_sha,
            "diff_mode": pr_input.diff_mode,
        },
        "aspect_input_policy": {
            "no_sot_aspects": sorted(no_sot_aspects),
        },
        "aspects": {
            "index_path": os.path.relpath(
                str(aspects_result["index_path"]), os.getcwd()
            ),
            "evidence_index_path": os.path.relpath(evidence_index_path, os.getcwd()),
            "policy_index_path": os.path.relpath(policy_index_path, os.getcwd()),
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
            "tool_bundle_files": list(tool_bundle_files),
            "evidence_json": os.path.relpath(evidence_json_path, os.getcwd()),
            "review_summary_json": os.path.relpath(summary_json_path, os.getcwd())
            if summary_json_path
            else "",
            "review_summary_md": os.path.relpath(summary_md_path, os.getcwd())
            if summary_md_path
            else "",
            "summary_comment": post_result,
            "inline_comment": inline_result,
            "aspects_evidence_index_json": os.path.relpath(
                evidence_index_path, os.getcwd()
            ),
            "aspects_policy_index_json": os.path.relpath(
                policy_index_path, os.getcwd()
            ),
            "re_run_plan_json": os.path.relpath(rerun_plan_path, os.getcwd())
            if rerun_plan_path
            else "",
            "state_json": os.path.relpath(state_json_path, os.getcwd()),
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

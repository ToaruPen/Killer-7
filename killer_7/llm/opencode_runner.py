"""OpenCode runner (headless subprocess).

This module runs `opencode` as a subprocess and captures JSONL events.

Scope (Issue #6):
- One viewpoint at a time
- Timeout per viewpoint
- On invalid/missing JSON output: leave error artifacts and fail with ExecFailureError
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, NoReturn

from ..artifacts import atomic_write_text_secure
from ..errors import BlockedError, ExecFailureError
from ..explore.policy import validate_git_readonly_bash_command
from .output_extract import (
    extract_json_and_tool_uses_from_jsonl_lines,
    extract_json_from_jsonl_lines,
)


def _opencode_bin() -> str:
    return os.environ.get("KILLER7_OPENCODE_BIN", "opencode")


def _slugify(value: str) -> str:
    s = (value or "").strip().lower()
    out: list[str] = []
    prev_dash = False
    for ch in s:
        ok = ("a" <= ch <= "z") or ("0" <= ch <= "9")
        if ok:
            out.append(ch)
            prev_dash = False
            continue
        if not prev_dash:
            out.append("-")
            prev_dash = True
    slug = "".join(out).strip("-")
    slug = slug[:60]
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]
    if not slug:
        slug = "viewpoint"
    return f"{slug}-{h}"


def opencode_artifacts_dir(out_dir: str, viewpoint: str) -> str:
    return os.path.join(out_dir, "opencode", _slugify(viewpoint))


def _repo_root_from_out_dir(out_dir: str) -> str:
    real_out = os.path.realpath(out_dir or ".")
    if os.path.basename(real_out) == ".ai-review":
        parent = os.path.dirname(real_out) or "."
        return os.path.realpath(parent)
    return real_out


def _atomic_write_text(path: str, content: str) -> None:
    dir_name = os.path.dirname(path) or "."
    base = os.path.basename(path)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=dir_name,
        prefix=f".{base}.tmp.",
    ) as fh:
        tmp = fh.name
        fh.write(content)
        if content and (not content.endswith("\n")):
            fh.write("\n")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _atomic_write_json(path: str, payload: object) -> None:
    dir_name = os.path.dirname(path) or "."
    base = os.path.basename(path)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=dir_name,
        prefix=f".{base}.tmp.",
    ) as fh:
        tmp = fh.name
        fh.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        fh.write("\n")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _truncate(s: str, max_chars: int = 2000) -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "... [truncated]"


def _truncate_tail(s: str, max_chars: int = 2000) -> str:
    if len(s) <= max_chars:
        return s
    keep = max_chars - 20
    return "... [truncated]" + s[-keep:]


def _redact_secrets(text: str) -> str:
    if not text:
        return text

    out = text
    # Common header-style tokens.
    out = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+", "Bearer <REDACTED>", out)
    # KEY=VALUE / KEY: VALUE
    out = re.sub(
        r"(?im)\b([A-Z0-9_]{2,64}_(?:TOKEN|KEY|SECRET))\b\s*[:=]\s*\S+",
        r"\1=<REDACTED>",
        out,
    )
    # Explicit names.
    out = re.sub(
        r"(?im)\b(api[_-]?key|token|secret)\b\s*[:=]\s*\S+",
        r"\1=<REDACTED>",
        out,
    )
    return out


def _sanitize_bundle_text(value: object) -> str:
    s = "" if value is None else str(value)
    out: list[str] = []
    for ch in s:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif code < 32 or code == 127:
            out.append(f"\\x{code:02x}")
        else:
            out.append(ch)
    return "".join(out)


def _write_redacted_opencode_jsonl(
    src_path: str, dst_path: str, *, repo_root: str
) -> None:
    dir_name = os.path.dirname(dst_path) or "."
    base = os.path.basename(dst_path)
    tmp = ""

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=dir_name,
            prefix=f".{base}.tmp.",
        ) as out:
            tmp = out.name
            with open(src_path, "r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    line = (raw or "").rstrip("\n")
                    if not line:
                        continue
                    if not line.lstrip().startswith("{"):
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(obj, dict):
                        continue

                    if obj.get("type") != "tool_use":
                        continue

                    part = obj.get("part")
                    if isinstance(part, dict):
                        state = part.get("state")
                        if isinstance(state, dict):
                            inp = state.get("input")
                            if isinstance(inp, dict):
                                fp = inp.get("filePath")
                                if isinstance(fp, str) and fp.strip():
                                    abs_path = (
                                        fp
                                        if os.path.isabs(fp)
                                        else os.path.join(repo_root, fp)
                                    )
                                    real = os.path.realpath(abs_path)
                                    if real == repo_root or real.startswith(
                                        repo_root + os.sep
                                    ):
                                        rel = os.path.relpath(real, repo_root).replace(
                                            os.sep, "/"
                                        )
                                    else:
                                        rel = "<outside-repo>"
                                    inp["filePath"] = rel

                                base = inp.get("path")
                                if isinstance(base, str) and base.strip():
                                    abs_base = (
                                        base
                                        if os.path.isabs(base)
                                        else os.path.join(repo_root, base)
                                    )
                                    real_base = os.path.realpath(abs_base)
                                    if real_base == repo_root or real_base.startswith(
                                        repo_root + os.sep
                                    ):
                                        rel_base = os.path.relpath(
                                            real_base, repo_root
                                        ).replace(os.sep, "/")
                                    else:
                                        rel_base = "<outside-repo>"
                                    inp["path"] = rel_base

                                for k in ("pattern", "include"):
                                    v = inp.get(k)
                                    if isinstance(v, str) and v:
                                        inp[k] = _redact_secrets(v)

                                cmd = inp.get("command")
                                if isinstance(cmd, str) and cmd:
                                    inp["command"] = _redact_secrets(cmd)

                            if "output" in state:
                                state["output"] = ""
                            if "attachments" in state:
                                state["attachments"] = []
                    out.write(json.dumps(obj, ensure_ascii=False) + "\n")

        os.replace(tmp, dst_path)
        tmp = ""
        try:
            os.chmod(dst_path, 0o600)
        except OSError:
            pass
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _git_tracked_files(repo_root: str) -> set[str] | None:
    try:
        p = subprocess.run(
            [
                "git",
                "-C",
                repo_root,
                "ls-files",
                "-z",
            ],
            text=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return None

    if p.returncode != 0:
        return None

    out = p.stdout or b""
    paths: set[str] = set()
    for raw in out.split(b"\x00"):
        if not raw:
            continue
        try:
            s = raw.decode("utf-8", errors="replace")
        except Exception:
            continue
        rel = s.replace("\\", "/").strip("/")
        if rel:
            paths.add(rel)
    return paths


def _is_denied_explore_relpath(rel: str) -> bool:
    r = (rel or "").strip().lstrip("/")
    if not r:
        return True

    denied_exact = {".git", ".ai-review", ".agentic-sdd"}
    if r in denied_exact:
        return True

    for pref in (".git/", ".ai-review/", ".agentic-sdd/"):
        if r.startswith(pref):
            return True

    base = r.split("/")[-1]
    if base == ".env" or base.startswith(".env."):
        return True

    return False


def _explore_policy_violation(
    *, artifacts_dir: str, cmd: list[str], message: str
) -> NoReturn:
    _atomic_write_json(
        os.path.join(artifacts_dir, "error.json"),
        {
            "schema_version": 1,
            "kind": "explore_policy_violation",
            "message": _truncate(message),
            "cmd": cmd,
        },
    )
    raise BlockedError(f"Explore policy violation: {message}")


def _env_int(env: dict[str, str] | None, key: str, default: int) -> int:
    if not env:
        return default
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _explore_limits(env: dict[str, str] | None) -> tuple[int, int, int, int, int]:
    return (
        _env_int(env, "KILLER7_EXPLORE_MAX_TOOL_CALLS", 200),
        _env_int(env, "KILLER7_EXPLORE_MAX_BASH_CALLS", 80),
        _env_int(env, "KILLER7_EXPLORE_MAX_READ_LINES", 2000),
        _env_int(env, "KILLER7_EXPLORE_MAX_FILES", 50),
        _env_int(env, "KILLER7_EXPLORE_MAX_BUNDLE_BYTES", 300_000),
    )


def _explore_validate_and_trace(
    *,
    artifacts_dir: str,
    cmd: list[str],
    repo_root: str,
    tool_uses: list[dict[str, Any]],
    max_tool_calls: int,
    max_bash_calls: int,
    max_read_lines: int,
) -> tuple[str, dict[str, set[int]]]:
    if max_tool_calls < 1 or max_bash_calls < 0 or max_read_lines < 1:
        raise ExecFailureError("Invalid explore limits")
    if len(tool_uses) > max_tool_calls:
        _explore_policy_violation(
            artifacts_dir=artifacts_dir,
            cmd=cmd,
            message=f"Too many tool calls (count={len(tool_uses)})",
        )

    allowed_tools = {"bash", "read", "grep", "glob"}
    tracked = _git_tracked_files(repo_root)
    if tracked is None:
        _explore_policy_violation(
            artifacts_dir=artifacts_dir,
            cmd=cmd,
            message="Failed to resolve git-tracked files (git ls-files failed)",
        )
    read_lines_by_path: dict[str, set[int]] = {}
    trace_lines: list[str] = []
    bash_calls = 0
    total_unique_read_lines = 0

    for e in tool_uses:
        part_obj = e.get("part")
        if not isinstance(part_obj, dict):
            _explore_policy_violation(
                artifacts_dir=artifacts_dir,
                cmd=cmd,
                message="Malformed tool_use event: missing part",
            )
        part = part_obj

        tool_name_obj = part.get("tool")
        tool_name = tool_name_obj if isinstance(tool_name_obj, str) else ""
        if not isinstance(tool_name, str) or not tool_name.strip():
            _explore_policy_violation(
                artifacts_dir=artifacts_dir,
                cmd=cmd,
                message="Malformed tool_use event: missing tool",
            )
        if tool_name not in allowed_tools:
            _explore_policy_violation(
                artifacts_dir=artifacts_dir,
                cmd=cmd,
                message=f"Forbidden tool: {tool_name}",
            )

        state_obj = part.get("state")
        if not isinstance(state_obj, dict):
            _explore_policy_violation(
                artifacts_dir=artifacts_dir,
                cmd=cmd,
                message=f"Malformed tool_use event: {tool_name}.state must be an object",
            )
        inp_obj2 = state_obj.get("input")
        if not isinstance(inp_obj2, dict):
            _explore_policy_violation(
                artifacts_dir=artifacts_dir,
                cmd=cmd,
                message=f"Malformed tool_use event: {tool_name}.state.input must be an object",
            )
        inp_obj = inp_obj2

        if tool_name == "bash":
            bash_calls += 1
            if bash_calls > max_bash_calls:
                _explore_policy_violation(
                    artifacts_dir=artifacts_dir,
                    cmd=cmd,
                    message=f"Too many bash calls (count={bash_calls})",
                )
            raw_cmd = inp_obj.get("command")
            bash_cmd = raw_cmd if isinstance(raw_cmd, str) else ""
            try:
                validate_git_readonly_bash_command(bash_cmd)
            except BlockedError as exc:
                msg = str(exc)
                prefix = "Explore policy violation: "
                if msg.startswith(prefix):
                    msg = msg[len(prefix) :]
                _explore_policy_violation(
                    artifacts_dir=artifacts_dir, cmd=cmd, message=msg
                )

            trace_lines.append(
                json.dumps(
                    {
                        "type": "tool_use",
                        "timestamp": e.get("timestamp"),
                        "sessionID": e.get("sessionID"),
                        "tool": "bash",
                        "callID": part.get("callID"),
                        "input": {"command": _redact_secrets(bash_cmd)},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            continue

        if tool_name in {"grep", "glob"}:
            base_obj = inp_obj.get("path")
            base = base_obj if isinstance(base_obj, str) else ""
            if not base.strip():
                base = "."
            abs_base = base if os.path.isabs(base) else os.path.join(repo_root, base)
            real_base = os.path.realpath(abs_base)
            if not (real_base == repo_root or real_base.startswith(repo_root + os.sep)):
                _explore_policy_violation(
                    artifacts_dir=artifacts_dir,
                    cmd=cmd,
                    message=f"{tool_name}.path must stay within repo root",
                )
            rel_base = os.path.relpath(real_base, repo_root).replace(os.sep, "/")
            if rel_base == ".":
                rel_base = ""
            if rel_base and _is_denied_explore_relpath(rel_base):
                _explore_policy_violation(
                    artifacts_dir=artifacts_dir,
                    cmd=cmd,
                    message=f"{tool_name}.path is forbidden in explore mode: {rel_base}",
                )

            if tool_name == "glob":
                pat_obj = inp_obj.get("pattern")
                pat = pat_obj if isinstance(pat_obj, str) else ""
                if not pat.strip():
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="glob.pattern is required",
                    )
                if os.path.isabs(pat):
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="glob.pattern must be repo-relative",
                    )
                norm = pat.replace("\\", "/")
                if ".." in norm.split("/"):
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="glob.pattern must not contain '..'",
                    )
                if norm.startswith(".git") or "/.git/" in norm:
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="glob.pattern must not target .git",
                    )
                if norm.startswith(".ai-review") or "/.ai-review/" in norm:
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="glob.pattern must not target .ai-review",
                    )
                if norm.startswith(".agentic-sdd") or "/.agentic-sdd/" in norm:
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="glob.pattern must not target .agentic-sdd",
                    )

                segs = [s for s in norm.split("/") if s]
                if any(s.startswith(".env") for s in segs):
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="glob.pattern must not target .env",
                    )

                base = segs[-1] if segs else norm
                if base in {"*", "**", "**/*"}:
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="glob.pattern is too broad",
                    )
                if "." not in base:
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="glob.pattern must include a file extension",
                    )

            if tool_name == "grep":
                pat_obj = inp_obj.get("pattern")
                pat = pat_obj if isinstance(pat_obj, str) else ""
                if not pat.strip():
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="grep.pattern is required",
                    )
                inc_obj = inp_obj.get("include")
                inc = inc_obj if isinstance(inc_obj, str) else ""
                if not inc.strip():
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="grep.include is required in explore mode",
                    )
                if os.path.isabs(inc):
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="grep.include must be repo-relative",
                    )
                norm = inc.replace("\\", "/")
                if ".." in norm.split("/"):
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="grep.include must not contain '..'",
                    )
                if norm in {"*", "**", "**/*"}:
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="grep.include is too broad",
                    )
                segs = [s for s in norm.split("/") if s]
                if any(s.startswith(".env") for s in segs):
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="grep.include must not target .env",
                    )
                if norm.startswith(".git") or "/.git/" in norm:
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="grep.include must not target .git",
                    )
                if norm.startswith(".ai-review") or "/.ai-review/" in norm:
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="grep.include must not target .ai-review",
                    )
                if norm.startswith(".agentic-sdd") or "/.agentic-sdd/" in norm:
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="grep.include must not target .agentic-sdd",
                    )

                base_inc = segs[-1] if segs else norm
                if "." not in base_inc:
                    _explore_policy_violation(
                        artifacts_dir=artifacts_dir,
                        cmd=cmd,
                        message="grep.include must include a file extension",
                    )

            inp_obj = dict(inp_obj)
            inp_obj["path"] = rel_base or "."

        if tool_name == "read":
            fp_obj = inp_obj.get("filePath")
            fp = fp_obj if isinstance(fp_obj, str) else ""
            if not fp.strip():
                _explore_policy_violation(
                    artifacts_dir=artifacts_dir,
                    cmd=cmd,
                    message="read.filePath is required",
                )

            abs_path = fp if os.path.isabs(fp) else os.path.join(repo_root, fp)
            real = os.path.realpath(abs_path)
            if not (real == repo_root or real.startswith(repo_root + os.sep)):
                _explore_policy_violation(
                    artifacts_dir=artifacts_dir,
                    cmd=cmd,
                    message="read.filePath must stay within repo root",
                )

            rel = os.path.relpath(real, repo_root).replace(os.sep, "/")
            if _is_denied_explore_relpath(rel):
                _explore_policy_violation(
                    artifacts_dir=artifacts_dir,
                    cmd=cmd,
                    message=f"read.filePath is forbidden in explore mode: {rel}",
                )
            if os.path.isdir(real):
                _explore_policy_violation(
                    artifacts_dir=artifacts_dir,
                    cmd=cmd,
                    message="read.filePath must be a file (directory reads are not allowed)",
                )
            if tracked is not None and rel not in tracked:
                _explore_policy_violation(
                    artifacts_dir=artifacts_dir,
                    cmd=cmd,
                    message=f"read.filePath must be a git-tracked file: {rel}",
                )

            off_obj = inp_obj.get("offset")
            lim_obj = inp_obj.get("limit")
            offset = off_obj if isinstance(off_obj, int) else 1
            limit = lim_obj if isinstance(lim_obj, int) else 200
            if offset < 1:
                offset = 1
            if limit < 1:
                limit = 1
            s = read_lines_by_path.setdefault(rel, set())
            if limit > max_read_lines:
                _explore_policy_violation(
                    artifacts_dir=artifacts_dir,
                    cmd=cmd,
                    message=(
                        f"read limit too large (limit={limit}, max={max_read_lines})"
                    ),
                )
            for n in range(offset, offset + limit):
                if n not in s:
                    s.add(n)
                    total_unique_read_lines += 1
                    if total_unique_read_lines > max_read_lines:
                        _explore_policy_violation(
                            artifacts_dir=artifacts_dir,
                            cmd=cmd,
                            message=(
                                f"Too many total read lines (count={total_unique_read_lines}, max={max_read_lines})"
                            ),
                        )

            inp_obj = dict(inp_obj)
            inp_obj["filePath"] = rel
            inp_obj["offset"] = offset
            inp_obj["limit"] = limit

        safe_inp = dict(inp_obj)
        for k in ("pattern", "include"):
            v = safe_inp.get(k)
            if isinstance(v, str) and v:
                safe_inp[k] = _redact_secrets(v)

        trace_lines.append(
            json.dumps(
                {
                    "type": "tool_use",
                    "timestamp": e.get("timestamp"),
                    "sessionID": e.get("sessionID"),
                    "tool": tool_name,
                    "callID": part.get("callID"),
                    "input": safe_inp,
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    return ("".join(trace_lines).rstrip("\n"), read_lines_by_path)


def _explore_tool_bundle_text(
    *,
    artifacts_dir: str,
    cmd: list[str],
    repo_root: str,
    read_lines_by_path: dict[str, set[int]],
    max_files: int,
    max_bytes: int,
) -> str:
    if max_files < 1 or max_bytes < 1:
        raise ExecFailureError("Invalid explore limits")
    if len(read_lines_by_path) > max_files:
        _explore_policy_violation(
            artifacts_dir=artifacts_dir,
            cmd=cmd,
            message=f"Too many files read (count={len(read_lines_by_path)})",
        )

    out_chunks: list[str] = []
    used = 0
    for rel_path in sorted(read_lines_by_path.keys()):
        header = f"# SRC: {_sanitize_bundle_text(rel_path)}\n"
        if used + len(header.encode("utf-8")) > max_bytes:
            _explore_policy_violation(
                artifacts_dir=artifacts_dir, cmd=cmd, message="tool bundle too large"
            )
        out_chunks.append(header)
        used += len(header.encode("utf-8"))

        wanted = sorted(read_lines_by_path.get(rel_path, set()))
        for n in wanted:
            row = f"L{n}: <redacted>\n"
            if used + len(row.encode("utf-8")) > max_bytes:
                _explore_policy_violation(
                    artifacts_dir=artifacts_dir,
                    cmd=cmd,
                    message="tool bundle too large",
                )
            out_chunks.append(row)
            used += len(row.encode("utf-8"))

    return "".join(out_chunks).rstrip("\n")


def _write_explore_trace_and_bundle(
    *,
    artifacts_dir: str,
    cmd: list[str],
    out_dir: str,
    tool_uses: list[dict[str, Any]],
    env: dict[str, str] | None,
) -> None:
    repo_root = _repo_root_from_out_dir(out_dir)
    max_tool_calls, max_bash_calls, max_read_lines, max_files, max_bytes = (
        _explore_limits(env)
    )

    trace_txt, read_lines_by_path = _explore_validate_and_trace(
        artifacts_dir=artifacts_dir,
        cmd=cmd,
        repo_root=repo_root,
        tool_uses=tool_uses,
        max_tool_calls=max_tool_calls,
        max_bash_calls=max_bash_calls,
        max_read_lines=max_read_lines,
    )
    atomic_write_text_secure(
        os.path.join(artifacts_dir, "tool-trace.jsonl"), (trace_txt or "").rstrip("\n")
    )

    bundle_txt = _explore_tool_bundle_text(
        artifacts_dir=artifacts_dir,
        cmd=cmd,
        repo_root=repo_root,
        read_lines_by_path=read_lines_by_path,
        max_files=max_files,
        max_bytes=max_bytes,
    )
    atomic_write_text_secure(
        os.path.join(artifacts_dir, "tool-bundle.txt"), (bundle_txt or "").rstrip("\n")
    )


def _read_file_truncated(path: str, *, max_bytes: int, tail_bytes: int = 4096) -> str:
    if max_bytes <= 0:
        return ""

    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0

    marker = b"\n\n[TRUNCATED]\n\n"
    if size <= max_bytes:
        with open(path, "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8", errors="replace")
        return text if text.endswith("\n") else (text + "\n")

    budget = max_bytes - len(marker)
    if budget <= 0:
        out = marker[:max_bytes]
        text = out.decode("utf-8", errors="replace")
        return text if text.endswith("\n") else (text + "\n")

    tail_len = min(tail_bytes, budget)
    head_len = budget - tail_len

    with open(path, "rb") as fh:
        head = fh.read(head_len) if head_len > 0 else b""
        if tail_len > 0:
            fh.seek(-tail_len, os.SEEK_END)
            tail = fh.read(tail_len)
        else:
            tail = b""

    out = head + marker + tail
    text = out.decode("utf-8", errors="replace")
    return text if text.endswith("\n") else (text + "\n")


MAX_STDIO_BYTES = 100 * 1024


@dataclass(frozen=True)
class OpenCodeRunner:
    bin_path: str = "opencode"
    timeout_s: int = 300
    agent: str | None = None
    model: str | None = None

    @classmethod
    def from_env(cls) -> "OpenCodeRunner":
        agent = os.environ.get("KILLER7_OPENCODE_AGENT")
        model = os.environ.get("KILLER7_OPENCODE_MODEL")
        timeout_s = os.environ.get("KILLER7_OPENCODE_TIMEOUT_S")
        timeout = 300
        if isinstance(timeout_s, str) and timeout_s.strip():
            try:
                timeout = int(timeout_s)
            except ValueError as exc:
                raise ExecFailureError(
                    f"Invalid KILLER7_OPENCODE_TIMEOUT_S: {timeout_s!r} (expected integer seconds)"
                ) from exc
            if timeout <= 0:
                raise ExecFailureError(
                    f"Invalid KILLER7_OPENCODE_TIMEOUT_S: {timeout_s!r} (must be >= 1)"
                )
        return cls(
            bin_path=_opencode_bin(), timeout_s=timeout, agent=agent, model=model
        )

    def _build_cmd(self) -> list[str]:
        cmd: list[str] = [self.bin_path, "run", "--format", "json"]
        if self.agent:
            cmd.extend(["--agent", self.agent])
        if self.model:
            cmd.extend(["-m", self.model])
        return cmd

    def _artifact_dir(self, out_dir: str, viewpoint: str) -> str:
        return opencode_artifacts_dir(out_dir, viewpoint)

    def run_viewpoint(
        self,
        *,
        out_dir: str,
        viewpoint: str,
        message: str,
        timeout_s: int | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Run OpenCode for a single viewpoint and write artifacts.

        Success:
        - writes `review-<viewpoint_slug>.json` under out_dir

        Failure:
        - writes error artifacts under `out_dir/opencode/<viewpoint_slug>/`
        - raises BlockedError (missing binary) or ExecFailureError (exec failure)
        """

        if not out_dir:
            raise ExecFailureError("out_dir is required")

        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            raise ExecFailureError(f"Failed to create out_dir: {out_dir}") from exc

        artifacts_dir = self._artifact_dir(out_dir, viewpoint)
        cmd = self._build_cmd()

        def ensure_artifacts_dir() -> None:
            os.makedirs(artifacts_dir, mode=0o700, exist_ok=True)
            try:
                os.chmod(artifacts_dir, 0o700)
            except OSError:
                pass

        effective_timeout = self.timeout_s if timeout_s is None else timeout_s
        if not isinstance(effective_timeout, int) or effective_timeout <= 0:
            ensure_artifacts_dir()
            _atomic_write_json(
                os.path.join(artifacts_dir, "error.json"),
                {
                    "schema_version": 1,
                    "kind": "invalid_timeout",
                    "message": f"Invalid timeout_s: {effective_timeout!r} (must be >= 1)",
                    "cmd": cmd,
                },
            )
            raise ExecFailureError(
                f"Invalid timeout_s: {effective_timeout!r} (must be >= 1)"
            )

        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        explore_requested = False
        if env:
            explore_requested = (env.get("KILLER7_EXPLORE") or "").strip() == "1"

        if explore_requested:
            merged_env["KILLER7_EXPLORE"] = "1"
        else:
            merged_env.pop("KILLER7_EXPLORE", None)

        explore_enabled = (merged_env.get("KILLER7_EXPLORE") or "").strip() == "1"

        bad_env: list[str] = []
        for k, v in merged_env.items():
            if not isinstance(k, str) or not isinstance(v, str):
                bad_env.append(str(k))
        if bad_env:
            ensure_artifacts_dir()
            _atomic_write_json(
                os.path.join(artifacts_dir, "error.json"),
                {
                    "schema_version": 1,
                    "kind": "invalid_env",
                    "message": "Environment variables must be strings",
                    "bad_keys": bad_env[:20],
                    "cmd": cmd,
                },
            )
            raise ExecFailureError("Environment variables must be strings")

        stdout_path = ""
        stderr_path = ""
        stdout_jsonl_path = ""
        stdout_text = ""
        stderr_text = ""

        def cleanup_tmp() -> None:
            nonlocal stdout_path, stderr_path
            if stdout_path:
                try:
                    os.remove(stdout_path)
                except OSError:
                    pass
            if stderr_path:
                try:
                    os.remove(stderr_path)
                except OSError:
                    pass

        def persist_redacted_stdout_jsonl_for_failure() -> None:
            if not explore_enabled:
                return
            if not stdout_path:
                return

            ensure_artifacts_dir()
            dst = os.path.join(artifacts_dir, "stdout.jsonl")
            repo_root = _repo_root_from_out_dir(out_dir)

            max_jsonl_bytes = 2_000_000
            raw = (
                merged_env.get("KILLER7_EXPLORE_MAX_STDOUT_JSONL_BYTES") or ""
            ).strip()
            if raw:
                try:
                    max_jsonl_bytes = int(raw)
                except ValueError:
                    max_jsonl_bytes = 2_000_000

            if max_jsonl_bytes < 1:
                return

            try:
                size = os.path.getsize(stdout_path)
            except OSError:
                return

            if size <= 0 or size > max_jsonl_bytes:
                return
            try:
                _write_redacted_opencode_jsonl(stdout_path, dst, repo_root=repo_root)
            except Exception:  # noqa: BLE001
                return

        try:
            with tempfile.NamedTemporaryFile(delete=False) as out_fh:
                stdout_path = out_fh.name
            with tempfile.NamedTemporaryFile(delete=False) as err_fh:
                stderr_path = err_fh.name

            with (
                open(stdout_path, "w", encoding="utf-8") as out_text,
                open(stderr_path, "w", encoding="utf-8") as err_text,
            ):
                p = subprocess.run(
                    cmd,
                    input=message,
                    text=True,
                    stdout=out_text,
                    stderr=err_text,
                    check=False,
                    timeout=effective_timeout,
                    env=merged_env,
                )
        except FileNotFoundError as exc:
            cleanup_tmp()
            ensure_artifacts_dir()
            _atomic_write_json(
                os.path.join(artifacts_dir, "error.json"),
                {
                    "schema_version": 1,
                    "kind": "missing_binary",
                    "message": "`opencode` is required. Install OpenCode and ensure it is on PATH.",
                    "cmd": cmd,
                    "bin_path": self.bin_path,
                },
            )
            raise BlockedError(
                "`opencode` is required. Install OpenCode and ensure it is on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            ensure_artifacts_dir()

            if explore_enabled:
                persist_redacted_stdout_jsonl_for_failure()
            else:
                if stdout_path:
                    stdout_text = _read_file_truncated(
                        stdout_path, max_bytes=MAX_STDIO_BYTES, tail_bytes=4096
                    )
                    stdout_text = _redact_secrets(stdout_text)
                    _atomic_write_text(
                        os.path.join(artifacts_dir, "stdout.txt"), stdout_text
                    )
                if stderr_path:
                    stderr_text = _read_file_truncated(
                        stderr_path, max_bytes=MAX_STDIO_BYTES, tail_bytes=4096
                    )
                    stderr_text = _redact_secrets(stderr_text)
                    _atomic_write_text(
                        os.path.join(artifacts_dir, "stderr.txt"), stderr_text
                    )

            _atomic_write_json(
                os.path.join(artifacts_dir, "error.json"),
                {
                    "schema_version": 1,
                    "kind": "timeout",
                    "message": f"OpenCode timed out after {effective_timeout}s",
                    "cmd": cmd,
                },
            )
            cleanup_tmp()
            raise ExecFailureError(
                f"OpenCode timed out after {effective_timeout}s"
            ) from exc
        except (OSError, ValueError, TypeError) as exc:
            ensure_artifacts_dir()
            msg = _truncate(f"OpenCode subprocess failed: {type(exc).__name__}: {exc}")
            _atomic_write_json(
                os.path.join(artifacts_dir, "error.json"),
                {
                    "schema_version": 1,
                    "kind": "subprocess_error",
                    "message": msg,
                    "cmd": cmd,
                },
            )
            cleanup_tmp()
            raise ExecFailureError(msg) from exc

        if stdout_path:
            try:
                stdout_text = _read_file_truncated(
                    stdout_path, max_bytes=MAX_STDIO_BYTES, tail_bytes=4096
                )
            except OSError as exc:
                ensure_artifacts_dir()
                msg = _truncate(
                    f"Failed to read OpenCode stdout: {type(exc).__name__}: {exc}"
                )
                _atomic_write_json(
                    os.path.join(artifacts_dir, "error.json"),
                    {
                        "schema_version": 1,
                        "kind": "subprocess_error",
                        "message": msg,
                        "cmd": cmd,
                    },
                )
                cleanup_tmp()
                raise ExecFailureError(msg) from exc
        if stderr_path:
            try:
                stderr_text = _read_file_truncated(
                    stderr_path, max_bytes=MAX_STDIO_BYTES, tail_bytes=4096
                )
            except OSError as exc:
                ensure_artifacts_dir()
                msg = _truncate(
                    f"Failed to read OpenCode stderr: {type(exc).__name__}: {exc}"
                )
                _atomic_write_json(
                    os.path.join(artifacts_dir, "error.json"),
                    {
                        "schema_version": 1,
                        "kind": "subprocess_error",
                        "message": msg,
                        "cmd": cmd,
                    },
                )
                cleanup_tmp()
                raise ExecFailureError(msg) from exc

        stdout_text = _redact_secrets(stdout_text)
        stderr_text = _redact_secrets(stderr_text)

        if p.returncode != 0:
            ensure_artifacts_dir()
            if explore_enabled:
                persist_redacted_stdout_jsonl_for_failure()
            else:
                _atomic_write_text(
                    os.path.join(artifacts_dir, "stdout.txt"),
                    stdout_text,
                )
                _atomic_write_text(
                    os.path.join(artifacts_dir, "stderr.txt"),
                    stderr_text,
                )
            msg_src = (stderr_text or "").strip()
            msg = msg_src or f"OpenCode failed (exit={p.returncode})"
            msg = _truncate_tail(_redact_secrets(msg))
            _atomic_write_json(
                os.path.join(artifacts_dir, "error.json"),
                {
                    "schema_version": 1,
                    "kind": "nonzero_exit",
                    "message": msg,
                    "exit_code": p.returncode,
                    "cmd": cmd,
                },
            )
            cleanup_tmp()
            raise ExecFailureError(msg)

        try:
            stdout_jsonl_path = ""
            if explore_enabled and stdout_path:
                ensure_artifacts_dir()
                stdout_jsonl_path = os.path.join(artifacts_dir, "stdout.jsonl")
                max_jsonl_bytes = 2_000_000
                mjb = (
                    merged_env.get("KILLER7_EXPLORE_MAX_STDOUT_JSONL_BYTES") or ""
                ).strip()
                if mjb:
                    try:
                        max_jsonl_bytes = int(mjb)
                    except ValueError:
                        pass
                if max_jsonl_bytes < 1:
                    raise ExecFailureError("Invalid explore limits")
                try:
                    size = os.path.getsize(stdout_path)
                except OSError:
                    size = 0
                if size > max_jsonl_bytes:
                    _atomic_write_json(
                        os.path.join(artifacts_dir, "error.json"),
                        {
                            "schema_version": 1,
                            "kind": "explore_policy_violation",
                            "message": f"OpenCode JSONL too large (bytes={size})",
                            "cmd": cmd,
                        },
                    )
                    raise BlockedError(
                        "Explore policy violation: OpenCode JSONL too large"
                    )

            if not stdout_path:
                raise ExecFailureError("Missing OpenCode stdout capture")
            with open(stdout_path, "r", encoding="utf-8", errors="replace") as fh:
                tool_uses: list[dict[str, Any]] = []
                if explore_enabled:
                    payload, tool_uses = extract_json_and_tool_uses_from_jsonl_lines(fh)
                else:
                    payload = extract_json_from_jsonl_lines(fh)

            if explore_enabled:
                ensure_artifacts_dir()
                _write_explore_trace_and_bundle(
                    artifacts_dir=artifacts_dir,
                    cmd=cmd,
                    out_dir=out_dir,
                    tool_uses=tool_uses,
                    env=merged_env,
                )

                if stdout_jsonl_path:
                    try:
                        repo_root = _repo_root_from_out_dir(out_dir)
                        _write_redacted_opencode_jsonl(
                            stdout_path,
                            stdout_jsonl_path,
                            repo_root=repo_root,
                        )
                        try:
                            os.remove(stdout_path)
                        except OSError:
                            pass
                        stdout_path = ""
                    except Exception as exc:  # noqa: BLE001
                        _atomic_write_json(
                            os.path.join(artifacts_dir, "error.json"),
                            {
                                "schema_version": 1,
                                "kind": "explore_trace_write_failed",
                                "message": _truncate(
                                    f"Failed to persist OpenCode JSONL: {type(exc).__name__}: {exc}"
                                ),
                                "cmd": cmd,
                            },
                        )
                        raise ExecFailureError(
                            _truncate(f"Failed to persist OpenCode JSONL: {exc}")
                        ) from exc
        except BlockedError as exc:
            ensure_artifacts_dir()
            if not explore_enabled:
                _atomic_write_text(
                    os.path.join(artifacts_dir, "stdout.txt"),
                    stdout_text,
                )
                _atomic_write_text(
                    os.path.join(artifacts_dir, "stderr.txt"),
                    stderr_text,
                )
            else:
                err_path = os.path.join(artifacts_dir, "error.json")
                if not os.path.exists(err_path):
                    _atomic_write_json(
                        err_path,
                        {
                            "schema_version": 1,
                            "kind": "blocked",
                            "message": _truncate(_redact_secrets(str(exc))),
                            "cmd": cmd,
                        },
                    )
            raise
        except ExecFailureError as exc:
            ensure_artifacts_dir()
            if explore_enabled:
                persist_redacted_stdout_jsonl_for_failure()
            else:
                _atomic_write_text(
                    os.path.join(artifacts_dir, "stdout.txt"),
                    stdout_text,
                )
                _atomic_write_text(
                    os.path.join(artifacts_dir, "stderr.txt"),
                    stderr_text,
                )
            _atomic_write_json(
                os.path.join(artifacts_dir, "error.json"),
                {
                    "schema_version": 1,
                    "kind": "invalid_output",
                    "message": _truncate(_redact_secrets(str(exc))),
                    "cmd": cmd,
                },
            )
            raise
        except OSError as exc:
            ensure_artifacts_dir()
            if explore_enabled:
                persist_redacted_stdout_jsonl_for_failure()
            else:
                _atomic_write_text(
                    os.path.join(artifacts_dir, "stdout.txt"),
                    stdout_text,
                )
                _atomic_write_text(
                    os.path.join(artifacts_dir, "stderr.txt"),
                    stderr_text,
                )
            msg = _truncate(
                f"OpenCode output processing failed: {type(exc).__name__}: {exc}"
            )
            _atomic_write_json(
                os.path.join(artifacts_dir, "error.json"),
                {
                    "schema_version": 1,
                    "kind": "invalid_output",
                    "message": _redact_secrets(msg),
                    "cmd": cmd,
                },
            )
            raise ExecFailureError(_redact_secrets(msg)) from exc
        finally:
            cleanup_tmp()

        result_name = f"review-{_slugify(viewpoint)}.json"
        result_path = os.path.join(out_dir, result_name)
        _atomic_write_json(result_path, payload)
        return {
            "viewpoint": viewpoint,
            "result_path": result_path,
            "payload": payload,
        }

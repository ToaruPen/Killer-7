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

from ..errors import BlockedError, ExecFailureError
from .output_extract import extract_json_from_jsonl_lines


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
        slug = _slugify(viewpoint)
        d = os.path.join(out_dir, "opencode", slug)
        return d

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
            if not stdout_path:
                raise ExecFailureError("Missing OpenCode stdout capture")
            with open(stdout_path, "r", encoding="utf-8", errors="replace") as fh:
                payload = extract_json_from_jsonl_lines(fh)
        except ExecFailureError as exc:
            ensure_artifacts_dir()
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
            cleanup_tmp()
            raise
        except OSError as exc:
            ensure_artifacts_dir()
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
            cleanup_tmp()
            raise ExecFailureError(_redact_secrets(msg)) from exc

        cleanup_tmp()

        result_name = f"review-{_slugify(viewpoint)}.json"
        result_path = os.path.join(out_dir, result_name)
        _atomic_write_json(result_path, payload)
        return {
            "viewpoint": viewpoint,
            "result_path": result_path,
            "payload": payload,
        }

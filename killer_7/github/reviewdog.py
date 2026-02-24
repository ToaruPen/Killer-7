from __future__ import annotations

import os
import subprocess

from ..errors import ExecFailureError

DEFAULT_REVIEWDOG_TIMEOUT_S = 60
MIN_REVIEWDOG_TIMEOUT_S = 1
TAIL_MAX_CHARS = 1200
TAIL_TRUNC_PREFIX = "... [truncated]"


def _reviewdog_bin() -> str:
    return os.environ.get("KILLER7_REVIEWDOG_BIN", "reviewdog")


def _reviewdog_timeout_s() -> int:
    raw = (
        os.environ.get("KILLER7_REVIEWDOG_TIMEOUT_S", str(DEFAULT_REVIEWDOG_TIMEOUT_S))
        or ""
    ).strip()
    try:
        timeout_s = int(raw)
    except ValueError as exc:
        raise ExecFailureError(
            "KILLER7_REVIEWDOG_TIMEOUT_S must be a positive integer"
        ) from exc
    if timeout_s <= 0:
        raise ExecFailureError(
            f"KILLER7_REVIEWDOG_TIMEOUT_S must be >= {MIN_REVIEWDOG_TIMEOUT_S}"
        )
    return timeout_s


def _tail(text: str, *, max_chars: int = TAIL_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    prefix_len = len(TAIL_TRUNC_PREFIX)
    if max_chars <= prefix_len:
        return TAIL_TRUNC_PREFIX[:max_chars]
    return TAIL_TRUNC_PREFIX + text[-(max_chars - prefix_len) :]


def run_reviewdog_from_sarif(
    *,
    sarif_path: str,
    reporter: str,
    filter_mode: str = "added",
    name: str = "killer-7-sarif",
    level: str = "warning",
) -> dict[str, object]:
    try:
        with open(sarif_path, "r", encoding="utf-8") as fh:
            sarif_text = fh.read()
    except OSError as exc:
        raise ExecFailureError(
            f"Failed to read SARIF file: {sarif_path}: {type(exc).__name__}: {exc}"
        ) from exc

    cmd = [
        _reviewdog_bin(),
        "-f=sarif",
        f"-name={name}",
        f"-reporter={reporter}",
        f"-filter-mode={filter_mode}",
        f"-level={level}",
    ]

    env = os.environ.copy()
    if "REVIEWDOG_GITHUB_API_TOKEN" not in env and "GITHUB_TOKEN" in env:
        env["REVIEWDOG_GITHUB_API_TOKEN"] = env["GITHUB_TOKEN"]

    timeout_s = _reviewdog_timeout_s()
    try:
        proc = subprocess.run(  # noqa: S603 - intentional local binary exec with shell=False
            cmd,
            input=sarif_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise ExecFailureError(f"reviewdog binary not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExecFailureError(f"reviewdog timed out after {timeout_s}s") from exc

    result: dict[str, object] = {}
    result["command"] = list(cmd)
    result["returncode"] = int(proc.returncode)
    result["stdout"] = proc.stdout
    result["stderr"] = proc.stderr
    if proc.returncode != 0:
        msg = _tail((proc.stderr or proc.stdout or "").strip())
        raise ExecFailureError(
            f"reviewdog failed (exit={proc.returncode}) on SARIF input: {msg}"
        )
    return result

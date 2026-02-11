from __future__ import annotations

import shlex
from collections.abc import Mapping


def _parse_diff_git_paths(line: str) -> tuple[str, str] | None:
    prefix = "diff --git "
    if not line.startswith(prefix):
        return None

    rest = line[len(prefix) :]
    try:
        parts = shlex.split(rest, posix=True)
    except ValueError:
        return None

    if len(parts) < 2:
        return None

    a_tok, b_tok = parts[0], parts[1]
    if not (a_tok.startswith("a/") and b_tok.startswith("b/")):
        return None
    return a_tok, b_tok


def _parse_path_token(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return ""
    try:
        parts = shlex.split(t, posix=True)
    except ValueError:
        return ""
    if len(parts) != 1:
        return ""
    return parts[0]


def build_right_line_to_position_map(
    patch: str | None,
) -> dict[str, dict[int, int]]:
    text = "" if patch is None else str(patch)
    lines = text.splitlines()

    out: dict[str, dict[int, int]] = {}

    cur_path: str | None = None
    cur_line_to_pos: dict[int, int] = {}
    cur_new_line: int | None = None
    cur_pos = 0

    def flush() -> None:
        nonlocal cur_path, cur_line_to_pos, cur_new_line, cur_pos
        if cur_path is not None and cur_line_to_pos:
            out[cur_path] = dict(cur_line_to_pos)
        cur_path = None
        cur_line_to_pos = {}
        cur_new_line = None
        cur_pos = 0

    for line in lines:
        if line.startswith("diff --git "):
            flush()
            toks = _parse_diff_git_paths(line)
            if toks is None:
                continue
            _, b_tok = toks
            b_path = b_tok[2:]
            cur_path = b_path or None
            continue

        if cur_path is None:
            continue

        if cur_new_line is None and line.startswith("+++ "):
            plus = _parse_path_token(line[4:])
            if plus.startswith("b/"):
                cur_path = plus[2:]
            continue

        if line.startswith("@@ "):
            if cur_new_line is not None:
                cur_pos += 1
            try:
                plus_part = line.split(" ")[2]
                new_start = plus_part[1:].split(",")[0]
                cur_new_line = int(new_start)
            except (IndexError, ValueError):
                cur_new_line = None
            continue

        if cur_new_line is None or not line:
            continue

        if line.startswith("\\"):
            cur_pos += 1
            continue

        prefix = line[0]
        if prefix not in {" ", "+", "-"}:
            continue

        cur_pos += 1

        if prefix in {" ", "+"}:
            cur_line_to_pos[cur_new_line] = cur_pos
            cur_new_line += 1
            continue

        if prefix == "-":
            continue

    flush()
    return out


def resolve_diff_position(
    line_map: Mapping[str, Mapping[int, int]],
    *,
    repo_relative_path: str,
    line: int,
) -> int | None:
    by_path = line_map.get(repo_relative_path)
    if by_path is None:
        return None
    pos = by_path.get(line)
    return pos if isinstance(pos, int) and pos > 0 else None

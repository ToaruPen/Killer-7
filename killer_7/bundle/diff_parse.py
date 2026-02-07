"""Parse unified diff patches for HEAD-side context extraction.

This module extracts the right-side (HEAD / b/) content from a unified diff.
It is designed for generating Context Bundle inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import shlex


@dataclass(frozen=True)
class SrcLine:
    """A single line on the HEAD/new side of a diff hunk."""

    new_line: int
    text: str


@dataclass(frozen=True)
class SrcBlock:
    """Collected HEAD-side lines for a single file."""

    path: str
    lines: tuple[SrcLine, ...]


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_diff_git_paths(line: str) -> tuple[str, str] | None:
    """Parse `diff --git <a> <b>` and return raw tokens.

    Supports quoted paths emitted by git for whitespace/special characters.
    """

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
    """Parse a single path token that may be quoted."""

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


def parse_diff_patch(patch: str) -> tuple[list[SrcBlock], list[str]]:
    """Parse a unified diff patch and extract HEAD-side blocks.

    Returns:
      (blocks, warnings)
    """

    text = "" if patch is None else str(patch)
    lines = text.splitlines()

    blocks: list[SrcBlock] = []
    warnings: list[str] = []

    cur_path: str | None = None
    cur_lines: list[SrcLine] = []
    cur_new_line: int | None = None
    cur_skip_kind: str | None = None

    def flush() -> None:
        nonlocal cur_path, cur_lines, cur_new_line, cur_skip_kind
        if cur_path is None:
            cur_lines = []
            cur_new_line = None
            cur_skip_kind = None
            return

        path = cur_path
        if cur_skip_kind is not None:
            warnings.append(f"diff_parse_skipped kind={cur_skip_kind} path={path}")
        elif not cur_lines:
            # Rename-only / mode-only file sections may have no hunks.
            warnings.append(f"diff_parse_skipped kind=no_hunks path={path}")
        else:
            blocks.append(SrcBlock(path=path, lines=tuple(cur_lines)))

        cur_path = None
        cur_lines = []
        cur_new_line = None
        cur_skip_kind = None

    for line in lines:
        if line.startswith("diff --git "):
            flush()
            toks = _parse_diff_git_paths(line)
            if toks is None:
                warnings.append("diff_parse_skipped kind=parse_failed path=")
                cur_path = None
                continue

            _, b_tok = toks
            b_path = b_tok[2:]
            cur_path = b_path or None
            continue

        if cur_path is None:
            continue

        if cur_skip_kind is not None:
            # Skip the remainder of this file section.
            continue

        if line.startswith("+++ "):
            plus = _parse_path_token(line[4:])
            if plus == "/dev/null":
                cur_skip_kind = "deleted"
            elif plus.startswith("b/"):
                # Prefer the +++ path when present.
                cur_path = plus[2:]
            continue

        if line.startswith("GIT binary patch") or line.startswith("Binary files "):
            cur_skip_kind = "binary"
            continue

        if line.startswith("@@"):
            hm = _HUNK_RE.match(line)
            if hm is None:
                cur_skip_kind = "parse_failed"
                cur_new_line = None
                continue

            try:
                cur_new_line = int(hm.group(3))
            except ValueError:
                cur_skip_kind = "parse_failed"
                cur_new_line = None
            continue

        if cur_new_line is None:
            continue

        if not line:
            # An empty line inside a hunk is a valid context/add line (prefix would still exist).
            continue

        prefix = line[0]
        if prefix == "\\":
            # "\\ No newline at end of file"
            continue

        if prefix == "+":
            cur_lines.append(SrcLine(new_line=cur_new_line, text=line[1:]))
            cur_new_line += 1
            continue

        if prefix == " ":
            cur_lines.append(SrcLine(new_line=cur_new_line, text=line[1:]))
            cur_new_line += 1
            continue

        if prefix == "-":
            # Deletions do not exist on HEAD/new side.
            continue

    flush()
    return blocks, warnings

"""Build Context Bundle text from HEAD-side diff blocks.

This module is pure (no file I/O). It applies line-count limits:

- max_file_lines: per-path contribution limit (includes the `# SRC:` header line)
- max_total_lines: overall bundle limit (includes all headers and content lines)

When limits are exceeded, it never truncates inside an SRC block.

Overflow semantics:
- If a block does not fit within the remaining `max_total_lines` budget, the
  block is dropped and we keep scanning later blocks that may still fit.
- We stop scanning only when there is not enough remaining budget to fit the
  smallest possible SRC block (header + 1 content line).
"""

from __future__ import annotations

from collections.abc import Iterable

from killer_7.bundle.diff_parse import SrcBlock


def _sanitize_kv_value(value: object) -> str:
    """Return a single-line, log-safe representation.

    This prevents path/control-character injection into `# SRC:` headers and
    warning lines.
    """

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


def build_context_bundle(
    blocks: Iterable[SrcBlock],
    *,
    max_total_lines: int = 1500,
    max_file_lines: int = 400,
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    out_lines: list[str] = []

    total_lines_used = 0
    file_lines_used: dict[str, int] = {}

    min_block_lines = 2  # header + at least one content line

    for block in blocks:
        raw_path = block.path
        safe_path = _sanitize_kv_value(raw_path)
        if not safe_path:
            warnings.append("context_bundle_block_skipped kind=empty_path")
            continue

        if not block.lines:
            warnings.append(f"context_bundle_block_skipped kind=empty path={safe_path}")
            continue

        required_lines = 1 + len(block.lines)

        already = file_lines_used.get(raw_path, 0)
        if already + required_lines > max_file_lines:
            warnings.append(
                "context_bundle_file_truncated"
                f" path={safe_path}"
                f" limit_lines={max_file_lines}"
                f" dropped_block_lines={required_lines}"
            )
            continue

        if total_lines_used + required_lines > max_total_lines:
            warnings.append(
                "context_bundle_total_truncated"
                f" limit_lines={max_total_lines}"
                f" path={safe_path}"
                f" dropped_block_lines={required_lines}"
            )
            if (max_total_lines - total_lines_used) < min_block_lines:
                break
            continue

        block_lines: list[str] = [f"# SRC: {safe_path}"]
        for src_line in block.lines:
            # src_line.text should be single-line already, but keep output log-safe.
            block_lines.append(
                f"L{src_line.new_line}: {_sanitize_kv_value(src_line.text)}"
            )

        out_lines.extend(block_lines)
        total_lines_used += required_lines
        file_lines_used[raw_path] = already + required_lines

    return "\n".join(out_lines) + ("\n" if out_lines else ""), warnings

"""SoT (Source of Truth) collection helpers.

This module focuses on assembling a deterministic SoT bundle from collected files.
The GitHub fetch/allowlist resolution is handled by existing GitHub utilities.
"""

from __future__ import annotations

from collections.abc import Mapping


def build_sot_markdown(
    contents_by_path: Mapping[str, str], *, max_lines: int
) -> tuple[str, list[str]]:
    """Build a SoT markdown bundle with a total line cap.

    Returns:
      (markdown_text, warnings)
    """

    limit = int(max_lines)
    if limit < 1:
        raise ValueError("max_lines must be >= 1")

    warnings: list[str] = []

    parts: list[str] = ["# SoT Bundle\n"]
    for path in sorted(set(contents_by_path.keys())):
        parts.append("\n")
        parts.append(f"# SRC: {path}\n")
        body = contents_by_path.get(path, "")
        body = "" if body is None else str(body)
        body = body.replace("\r\n", "\n").replace("\r", "\n")

        # Prefix SoT body lines to avoid ambiguity with `# SRC:` headers.
        # This also gives evidence verification a stable per-file line index.
        body_lines = body.rstrip("\n").split("\n") if body else [""]
        for i, line in enumerate(body_lines, start=1):
            parts.append(f"L{i}: {line}\n")

    text = "".join(parts)

    lines = text.splitlines(keepends=True)
    if len(lines) > limit:
        warnings.append(f"sot_truncated total_lines={len(lines)} limit_lines={limit}")
        text = "".join(lines[:limit])
        if not text.endswith("\n"):
            text += "\n"

    return text, warnings

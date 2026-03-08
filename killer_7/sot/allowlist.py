"""Default allowlist for SoT (Source of Truth) collection.

This list is intentionally small and repo-relative.
"""

from __future__ import annotations

DEFAULT_SOT_ALLOWLIST: list[str] = [
    # Root-level references
    "README.md",
    "CHANGELOG.md",
    "AGENTS.md",
    # Repository docs
    "docs/**/*.md",
]


def default_sot_allowlist() -> list[str]:
    # Return a copy to avoid accidental mutation.
    return list(DEFAULT_SOT_ALLOWLIST)

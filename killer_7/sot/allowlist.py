"""Default allowlist for SoT (Source of Truth) collection.

This list is intentionally small and repo-relative.
"""

from __future__ import annotations

DEFAULT_SOT_ALLOWLIST: list[str] = [
    # Project docs
    "docs/prd/**/*.md",
    "docs/epics/**/*.md",
    "docs/decisions.md",
    "docs/glossary.md",
    # Root-level references
    "README.md",
    "CHANGELOG.md",
    "AGENTS.md",
    # Agent rules (project governance)
    ".agent/commands/**/*.md",
    ".agent/rules/**/*.md",
]


def default_sot_allowlist() -> list[str]:
    # Return a copy to avoid accidental mutation.
    return list(DEFAULT_SOT_ALLOWLIST)

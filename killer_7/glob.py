"""Repo-relative glob helpers.

Use POSIX-style paths (forward slashes) regardless of host OS.
"""

from __future__ import annotations

import fnmatch
from functools import lru_cache


def normalize_repo_relative_path(path: str) -> str:
    """Normalize a repo-relative path.

    - Strips leading './' and '/'
    - Converts backslashes to slashes
    - Collapses repeated slashes
    """

    p = (path or "").strip()
    if not p:
        return ""

    p = p.replace("\\", "/")

    while p.startswith("./"):
        p = p[2:]
    while p.startswith("/"):
        p = p[1:]

    while "//" in p:
        p = p.replace("//", "/")

    segs = [s for s in p.split("/") if s != ""]
    # Disallow dot-segments to avoid allowlist bypass surprises.
    if any(s in (".", "..") for s in segs):
        return ""

    return "/".join(segs)


def filter_paths_by_globs(paths: list[str], patterns: list[str]) -> list[str]:
    """Return sorted, unique paths matching any of the glob patterns."""

    pats = [normalize_repo_relative_path(x) for x in patterns if (x or "").strip()]
    if not pats:
        return []

    matched: set[str] = set()
    for raw in paths:
        p = normalize_repo_relative_path(raw)
        if not p:
            continue

        for pat in pats:
            if _match_path_glob(p, pat):
                matched.add(p)
                break

    return sorted(matched)


@lru_cache(maxsize=4096)
def _match_path_glob(path: str, pattern: str) -> bool:
    """Match a repo-relative path against a glob pattern.

    Semantics:
    - Split on '/'
    - `*` / `?` do not cross directory boundaries
    - `**` (as a full segment) matches zero or more path segments
    """

    path_norm = normalize_repo_relative_path(path)
    pat_norm = normalize_repo_relative_path(pattern)
    if not pat_norm:
        return False

    path_segs = tuple([s for s in path_norm.split("/") if s != ""])
    pat_segs = tuple([s for s in pat_norm.split("/") if s != ""])

    @lru_cache(maxsize=None)
    def dp(i: int, j: int) -> bool:
        if j >= len(pat_segs):
            return i >= len(path_segs)

        seg = pat_segs[j]
        if seg == "**":
            # Match zero segments.
            if dp(i, j + 1):
                return True
            # Match one segment (if any) and keep '**'.
            return i < len(path_segs) and dp(i + 1, j)

        if i >= len(path_segs):
            return False

        if not fnmatch.fnmatchcase(path_segs[i], seg):
            return False

        return dp(i + 1, j + 1)

    return dp(0, 0)

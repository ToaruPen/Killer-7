from __future__ import annotations

from dataclasses import dataclass

from ..aspect_id import normalize_aspect
from ..errors import ExecFailureError


@dataclass(frozen=True)
class AspectHybridDecision:
    repo_read_only: bool
    allowlist_paths: tuple[str, ...]

    def runner_env(self) -> dict[str, str]:
        if not self.repo_read_only:
            return {"KILLER7_REPO_READONLY": "0"}
        return {
            "KILLER7_REPO_READONLY": "1",
            "KILLER7_REPO_ALLOWLIST": "\n".join(self.allowlist_paths),
        }


@dataclass(frozen=True)
class HybridPolicy:
    allowed_aspects: frozenset[str]
    allowlist_paths: tuple[str, ...]

    def decision_for(self, *, aspect: str) -> AspectHybridDecision:
        a = normalize_aspect(aspect)
        if a not in self.allowed_aspects:
            return AspectHybridDecision(repo_read_only=False, allowlist_paths=())
        if not self.allowlist_paths:
            return AspectHybridDecision(repo_read_only=False, allowlist_paths=())
        return AspectHybridDecision(
            repo_read_only=True,
            allowlist_paths=self.allowlist_paths,
        )


def _normalize_allowlist_pattern(value: str) -> str:
    if "\n" in (value or "") or "\r" in (value or ""):
        raise ExecFailureError("hybrid-allowlist must not contain newlines")
    p = (value or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    while p.startswith("/"):
        p = p[1:]
    while "//" in p:
        p = p.replace("//", "/")
    return p


def _contains_parent_traversal(path_pattern: str) -> bool:
    return any(seg == ".." for seg in path_pattern.split("/"))


def build_hybrid_policy(
    *,
    hybrid_aspects: list[str],
    hybrid_allowlist: list[str],
) -> HybridPolicy:
    aspects = frozenset(
        normalize_aspect(a) for a in hybrid_aspects if (a or "").strip()
    )

    normalized_allowlist: list[str] = []
    seen: set[str] = set()
    for raw in hybrid_allowlist:
        p = _normalize_allowlist_pattern(raw)
        if not p or p in seen:
            continue
        if _contains_parent_traversal(p):
            raise ExecFailureError(
                "hybrid-allowlist must stay within repository paths (no '..' segments)"
            )
        normalized_allowlist.append(p)
        seen.add(p)

    return HybridPolicy(
        allowed_aspects=aspects,
        allowlist_paths=tuple(normalized_allowlist),
    )

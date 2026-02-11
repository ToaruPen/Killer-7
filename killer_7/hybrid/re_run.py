from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone

from ..artifacts import atomic_write_json_secure
from ..aspect_id import normalize_aspect


def _build_run_id(*, head_sha: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_sha = (head_sha or "")[:12] or "unknownsha"
    return f"{ts}-{short_sha}"


@dataclass(frozen=True)
class ReRunArtifacts:
    run_id: str
    output_dir: str
    plan_path: str


def write_questions_rerun_artifacts(
    *,
    out_dir: str,
    repo: str,
    pr: int,
    head_sha: str,
    question_aspects: list[str],
    hybrid_allowlist: list[str],
) -> dict[str, str]:
    aspects: list[str] = []
    seen: set[str] = set()
    for raw in question_aspects:
        a = normalize_aspect(raw)
        if a in seen:
            continue
        aspects.append(a)
        seen.add(a)

    if not aspects:
        return {"run_id": "", "output_dir": "", "plan_path": ""}

    run_id = _build_run_id(head_sha=head_sha)
    re_run_dir = os.path.join(out_dir, "re-run", run_id)
    os.makedirs(re_run_dir, mode=0o700, exist_ok=True)

    allowlist: list[str] = []
    allowlist_seen: set[str] = set()
    for raw in hybrid_allowlist:
        p = (raw or "").strip()
        if not p or p in allowlist_seen:
            continue
        allowlist.append(p)
        allowlist_seen.add(p)

    hybrid_args = " ".join(f"--hybrid-aspect {shlex.quote(a)}" for a in aspects)
    allowlist_args = " ".join(f"--hybrid-allowlist {shlex.quote(p)}" for p in allowlist)
    cmd = f"killer-7 review --repo {shlex.quote(repo)} --pr {shlex.quote(str(pr))}"
    if hybrid_args:
        cmd += f" {hybrid_args}"
    if allowlist_args:
        cmd += f" {allowlist_args}"

    plan_path = os.path.join(re_run_dir, "plan.json")
    atomic_write_json_secure(
        plan_path,
        {
            "schema_version": 1,
            "kind": "questions_rerun_plan",
            "run_id": run_id,
            "repo": repo,
            "pr": pr,
            "head_sha": head_sha,
            "question_aspects": aspects,
            "hybrid_allowlist": allowlist,
            "output_dir": os.path.relpath(re_run_dir, os.getcwd()).replace(os.sep, "/"),
            "recommended_command": cmd,
        },
    )

    return {
        "run_id": run_id,
        "output_dir": re_run_dir,
        "plan_path": plan_path,
    }

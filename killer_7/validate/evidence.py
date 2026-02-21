from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import cast

_SRC_HEADER_RE = re.compile(r"^# SRC: (?P<path>.+?)\s*$")
_LINE_RE = re.compile(r"^L(?P<line>\d+):\s")

_SOURCE_REF_RE = re.compile(
    r"^(?P<path>[^#]+?)(?:#L(?P<start>\d+)(?:-L(?P<end>\d+))?)?$"
)


EVIDENCE_POLICY_V1: dict[str, object] = {
    "schema_version": 1,
    "unverified_strong_missing_sources": "exclude",
    "unverified_strong_other": "downgrade_to_P3",
}


def parse_context_bundle_index(text: str) -> dict[str, set[int]]:
    """Parse `context-bundle.txt` into an index.

    The index maps `# SRC:` paths to the set of line numbers seen in the corresponding
    SRC block.

    If lines are prefixed as `L<line>: ...`, those numbers are used. Otherwise, the
    parser falls back to assigning sequential line numbers within the SRC block.
    """

    idx: dict[str, set[int]] = {}
    current_path: str | None = None
    auto_line = 0

    for raw_line in (text or "").splitlines():
        if raw_line.strip() == "# SoT Bundle":
            current_path = None
            auto_line = 0
            continue

        m = _SRC_HEADER_RE.match(raw_line)
        if m:
            path = m.group("path")
            current_path = path
            auto_line = 0
            if path not in idx:
                idx[path] = set()
            continue

        if current_path is None:
            continue

        m = _LINE_RE.match(raw_line)
        if m:
            try:
                n = int(m.group("line"))
            except ValueError:
                continue
            if n < 1:
                continue
            idx[current_path].add(n)
            continue

        # If a SRC block doesn't prefix lines with `L<line>:` (unexpected but allowed),
        # index by sequential line numbers within the SRC block.
        auto_line += 1
        idx[current_path].add(auto_line)

    return idx


def _parse_source_ref(source: str) -> tuple[str, int | None, int | None] | None:
    s = (source or "").strip()
    if not s:
        return None
    m = _SOURCE_REF_RE.match(s)
    if not m:
        return None
    path = (m.group("path") or "").strip()
    if not path:
        return None

    start_s = m.group("start")
    end_s = m.group("end")
    if start_s is None and end_s is None:
        return (path, None, None)
    try:
        start = int(start_s) if start_s is not None else None
        end = int(end_s) if end_s is not None else start
    except ValueError:
        return None
    if start is None or end is None:
        return None
    if start < 1 or end < 1 or end < start:
        return None
    return (path, start, end)


def verify_finding_evidence(
    finding: Mapping[str, object],
    context_index: Mapping[str, set[int]],
) -> tuple[bool, str]:
    """Return (verified, reason).

    reason is one of:
    - "" (verified)
    - "missing_sources"
    - "invalid_sources" (sources exist but no entry parses)
    - "unresolved_source" (no sources resolve to any `# SRC:`)
    - "path_mismatch" (sources resolve, but none match code_location path)
    - "line_unverifiable" (path exists, but bundle contains no line index for it)
    - "line_mismatch" (path matches, but no indexed line falls within the expected range)
    """

    sources_obj = finding.get("sources")
    if not isinstance(sources_obj, list) or not sources_obj:
        return (False, "missing_sources")

    sources: list[object] = cast(list[object], sources_obj)

    parsed_sources: list[tuple[str, int | None, int | None]] = []
    saw_string = False
    for item_obj in sources:
        item = item_obj
        if not isinstance(item, str):
            continue
        saw_string = True
        ref = _parse_source_ref(item)
        if ref is None:
            continue
        parsed_sources.append(ref)
    if not parsed_sources:
        # Distinguish truly missing/empty sources from malformed source strings.
        return (False, "invalid_sources" if saw_string else "missing_sources")

    code_location_obj = finding.get("code_location")
    if not isinstance(code_location_obj, Mapping):
        return (False, "line_mismatch")

    code_location: Mapping[str, object] = cast(Mapping[str, object], code_location_obj)

    repo_relative_path = code_location.get("repo_relative_path")
    if not isinstance(repo_relative_path, str) or not repo_relative_path:
        return (False, "line_mismatch")

    line_range_obj = code_location.get("line_range")
    if not isinstance(line_range_obj, Mapping):
        return (False, "line_mismatch")

    line_range: Mapping[str, object] = cast(Mapping[str, object], line_range_obj)
    start = line_range.get("start")
    end = line_range.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return (False, "line_mismatch")
    if start < 1 or end < start:
        return (False, "line_mismatch")

    resolved_any = False
    matched_path = False

    for src_path, src_start, src_end in parsed_sources:
        if src_path not in context_index:
            continue
        resolved_any = True
        if src_path != repo_relative_path:
            continue
        matched_path = True

        line_set = context_index.get(src_path, set())
        if not line_set:
            return (False, "line_unverifiable")

        # Use a tighter range when the source specifies one.
        eff_start = start
        eff_end = end
        if src_start is not None and src_end is not None:
            eff_start = max(eff_start, src_start)
            eff_end = min(eff_end, src_end)
            if eff_end < eff_start:
                continue

        for n in line_set:
            if eff_start <= n <= eff_end:
                return (True, "")

    if not resolved_any:
        return (False, "unresolved_source")
    if not matched_path:
        return (False, "path_mismatch")
    return (False, "line_mismatch")


def apply_evidence_policy_to_findings(
    findings: list[object],
    context_index: Mapping[str, set[int]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Apply evidence verification + downgrade/exclude policy.

    Policy (Issue #10 decision):
    - If unverified because `sources` is missing/empty: exclude P0/P1/P2 findings.
    - If unverified for any other reason: downgrade P0/P1/P2 findings to P3.

    Returns:
      (out_findings, stats)
    """

    excluded = 0
    downgraded = 0
    verified_true = 0
    unverified_reason_counts: dict[str, int] = {}

    out: list[dict[str, object]] = []

    for item in findings:
        if not isinstance(item, dict):
            # Should not happen if upstream schema validation is enforced.
            continue

        finding = cast(dict[str, object], item)

        original_priority_obj = finding.get("priority")
        priority = (
            original_priority_obj if isinstance(original_priority_obj, str) else ""
        )

        verified, reason = verify_finding_evidence(finding, context_index)
        if verified:
            verified_true += 1
        else:
            unverified_reason_counts[reason] = (
                unverified_reason_counts.get(reason, 0) + 1
            )

        # Copy to avoid mutating upstream payload.
        f: dict[str, object] = dict(finding)
        f["verified"] = bool(verified)

        if not verified and priority in ("P0", "P1", "P2"):
            if reason == "missing_sources":
                excluded += 1
                continue

            # Downgrade to P3
            if "original_priority" not in f and priority:
                f["original_priority"] = priority
            f["priority"] = "P3"
            downgraded += 1

        out.append(f)

    stats: dict[str, object] = {
        "schema_version": 1,
        "total_in": len(findings),
        "total_out": len(out),
        "verified_true_count": verified_true,
        "excluded_count": excluded,
        "downgraded_count": downgraded,
        "unverified_reason_counts": dict(sorted(unverified_reason_counts.items())),
    }
    return out, stats


def recompute_review_status(
    findings: Sequence[object], questions: Sequence[object]
) -> str:
    """Recompute status from findings/questions to satisfy schema cross-field rules."""
    has_blocking = False
    for item in findings:
        if not isinstance(item, Mapping):
            continue
        m = cast(Mapping[str, object], item)
        pr = m.get("priority")
        if pr in ("P0", "P1"):
            has_blocking = True
            break

    if has_blocking:
        return "Blocked"
    if len(questions) > 0:
        return "Question"
    if len(findings) > 0:
        return "Approved with nits"
    return "Approved"

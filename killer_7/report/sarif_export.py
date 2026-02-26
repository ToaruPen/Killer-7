from __future__ import annotations

from collections.abc import Mapping

from .fingerprint import finding_fingerprint

_PRIORITY_TO_LEVEL = {
    "P0": "error",
    "P1": "error",
    "P2": "warning",
    "P3": "note",
}

_PROJECT_URL = "https://github.com/ToaruPen/Killer-7"
_SARIF_HELP_URI = (
    "https://github.com/ToaruPen/Killer-7/blob/main/docs/operations/sarif-reviewdog.md"
)
SARIF_RESULTS_DISPLAY_LIMIT = 5000
SARIF_RESULTS_HARD_LIMIT = 25000


def _coerce_str_object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, object] = {}
    for key_obj, mapped_value in value.items():
        if isinstance(key_obj, str):
            out[key_obj] = mapped_value
    return out


def _as_non_empty_str(value: object, *, fallback: str = "") -> str:
    if isinstance(value, str):
        s = value.strip()
        if s:
            return s
    return fallback


def _as_sources(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        s = _as_non_empty_str(item)
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _rule_for_priority(priority: str) -> dict[str, object]:
    if priority not in _PRIORITY_TO_LEVEL:
        raise ValueError(f"Unsupported priority for SARIF rule: {priority!r}")
    level = _PRIORITY_TO_LEVEL[priority]
    return {
        "id": f"K7.{priority}",
        "name": f"Killer-7 {priority}",
        "shortDescription": {"text": f"Killer-7 finding priority {priority}"},
        "defaultConfiguration": {"level": level},
        "helpUri": _SARIF_HELP_URI,
    }


def _finding_context(scope_id: str, finding: dict[str, object]) -> str:
    finding_id = _as_non_empty_str(finding.get("id"))
    finding_name = _as_non_empty_str(finding.get("name"))
    if finding_id:
        return f"scope_id={scope_id}, finding.id={finding_id!r}"
    if finding_name:
        return f"scope_id={scope_id}, finding.name={finding_name!r}"
    return (
        f"scope_id={scope_id}, finding_type={type(finding).__name__}, "
        f"finding_keys={sorted(finding.keys())}"
    )


def sarif_results_warning_line(*, findings_count: int) -> str | None:
    if findings_count <= SARIF_RESULTS_DISPLAY_LIMIT:
        return None
    if findings_count > SARIF_RESULTS_HARD_LIMIT:
        return None
    return (
        "sarif_result_limit_warning"
        f" findings={findings_count}"
        f" display_limit={SARIF_RESULTS_DISPLAY_LIMIT}"
        f" hard_limit={SARIF_RESULTS_HARD_LIMIT}"
        " note=github-code-scanning-may-silently-truncate-to-top-severity-results"
    )


def review_summary_to_sarif(summary: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(summary, Mapping):
        raise ValueError(
            "Invalid review summary: expected mapping at root "
            f"(summary_type={type(summary).__name__})"
        )
    scope_id = _as_non_empty_str(summary.get("scope_id"))
    if not scope_id:
        summary_keys = sorted(str(k) for k in summary.keys())
        raise ValueError(
            "Invalid review summary: missing required scope_id "
            f"(summary_type={type(summary).__name__}, summary_keys={summary_keys})"
        )
    raw_findings = summary.get("findings")
    if not isinstance(raw_findings, list):
        raise ValueError(
            "Invalid review summary: raw_findings must be a list to construct findings "
            f"(scope_id={scope_id}, raw_findings_type={type(raw_findings).__name__})"
        )
    findings = raw_findings
    findings_count = len(findings)
    if findings_count > SARIF_RESULTS_HARD_LIMIT:
        raise ValueError(
            "Invalid review summary: findings exceed SARIF hard limit "
            f"({findings_count} > {SARIF_RESULTS_HARD_LIMIT}). "
            "Split results into multiple runs or reduce findings before SARIF export."
        )

    results: list[dict[str, object]] = []
    priorities: set[str] = set()

    for item in findings:
        finding = _coerce_str_object_dict(item)
        priority = _as_non_empty_str(finding.get("priority"))
        if not priority:
            raise ValueError(
                f"Invalid finding priority: missing required priority ({_finding_context(scope_id, finding)})"
            )
        if priority not in _PRIORITY_TO_LEVEL:
            raise ValueError(
                f"Invalid finding priority: unsupported value {priority!r} ({_finding_context(scope_id, finding)})"
            )
        priorities.add(priority)

        code_location = _coerce_str_object_dict(finding.get("code_location"))
        if not code_location:
            raise ValueError("Invalid finding: missing code_location")
        line_range = _coerce_str_object_dict(code_location.get("line_range"))
        if not line_range:
            raise ValueError("Invalid finding: missing line_range")
        path = _as_non_empty_str(code_location.get("repo_relative_path"))
        if not path:
            raise ValueError("Invalid finding: missing repo_relative_path")

        start_raw = line_range.get("start")
        if (
            isinstance(start_raw, bool)
            or not isinstance(start_raw, int)
            or start_raw < 1
        ):
            raise ValueError("Invalid finding: line_range.start must be int >= 1")
        start = start_raw

        # line_range.end is optional; when omitted, it defaults to start.
        # This lets single-line ranges omit `end` while preserving explicit spans.
        end_raw = line_range.get("end", start)
        if isinstance(end_raw, bool) or not isinstance(end_raw, int) or end_raw < start:
            raise ValueError("Invalid finding: line_range.end must be int >= start")
        end = end_raw

        title = _as_non_empty_str(finding.get("title"))
        if not title:
            raise ValueError(
                f"Invalid finding: missing title ({_finding_context(scope_id, finding)})"
            )
        body = _as_non_empty_str(finding.get("body"))
        message = title if not body else f"{title}\n{body}"

        props: dict[str, object] = {
            "priority": priority,
            "sources": _as_sources(finding.get("sources")),
            "scope_id": scope_id,
        }
        if isinstance(finding.get("verified"), bool):
            props["verified"] = finding["verified"]
        original_priority = _as_non_empty_str(finding.get("original_priority"))
        if original_priority:
            props["original_priority"] = original_priority

        results.append(
            {
                "ruleId": f"K7.{priority}",
                "level": _PRIORITY_TO_LEVEL[priority],
                "message": {"text": message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": path},
                            "region": {
                                "startLine": start,
                                "endLine": end,
                            },
                        }
                    }
                ],
                "partialFingerprints": {
                    "k7/finding": finding_fingerprint(finding),
                },
                "properties": props,
            }
        )

    rules = [_rule_for_priority(p) for p in sorted(priorities)]

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Killer-7",
                        "informationUri": _PROJECT_URL,
                        "version": "v1",
                        "rules": rules,
                    }
                },
                "automationDetails": {
                    "id": "killer-7/review-summary",
                },
                "results": results,
            }
        ],
    }

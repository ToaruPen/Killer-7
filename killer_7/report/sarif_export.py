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


def _as_pos_int(value: object, *, fallback: int = 1) -> int:
    if isinstance(value, int) and value >= 1:
        return value
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
    level = _PRIORITY_TO_LEVEL.get(priority, "warning")
    return {
        "id": f"K7.{priority}",
        "name": f"Killer-7 {priority}",
        "shortDescription": {"text": f"Killer-7 finding priority {priority}"},
        "defaultConfiguration": {"level": level},
        "helpUri": _SARIF_HELP_URI,
    }


def review_summary_to_sarif(summary: Mapping[str, object]) -> dict[str, object]:
    scope_id = _as_non_empty_str(summary.get("scope_id"), fallback="unknown-scope")
    raw_findings = summary.get("findings")
    findings = raw_findings if isinstance(raw_findings, list) else []

    results: list[dict[str, object]] = []
    priorities: set[str] = set()

    for item in findings:
        finding = _coerce_str_object_dict(item)
        priority = _as_non_empty_str(finding.get("priority"), fallback="P3")
        if priority not in _PRIORITY_TO_LEVEL:
            priority = "P3"
        priorities.add(priority)

        code_location = _coerce_str_object_dict(finding.get("code_location"))
        line_range = _coerce_str_object_dict(code_location.get("line_range"))
        path = _as_non_empty_str(
            code_location.get("repo_relative_path"), fallback="unknown"
        )
        start = _as_pos_int(line_range.get("start"), fallback=1)
        end = _as_pos_int(line_range.get("end"), fallback=start)
        if end < start:
            end = start

        title = _as_non_empty_str(finding.get("title"), fallback="Finding")
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

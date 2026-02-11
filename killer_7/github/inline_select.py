from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from .diff_map import resolve_diff_position
from ..report.fingerprint import finding_fingerprint


@dataclass(frozen=True)
class InlineCandidate:
    title: str
    priority: str
    repo_relative_path: str
    start_line: int
    end_line: int
    diff_position: int | None
    inline_eligible: bool
    skip_reason: str
    fingerprint: str


def _as_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    mapping = cast(Mapping[object, object], value)
    out: dict[str, object] = {}
    for key_obj, mapped_value in mapping.items():
        if isinstance(key_obj, str):
            out[key_obj] = mapped_value
    return out


def _as_str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_line_range(code_location: Mapping[str, object]) -> tuple[int, int]:
    line_range_obj = _as_mapping(code_location.get("line_range"))
    start = line_range_obj.get("start")
    end = line_range_obj.get("end")
    start_line = start if isinstance(start, int) and start > 0 else 0
    end_line = end if isinstance(end, int) and end > 0 else 0
    return (start_line, end_line)


def select_inline_candidates(
    review_summary: Mapping[str, object],
    *,
    line_map: Mapping[str, Mapping[int, int]],
) -> list[InlineCandidate]:
    findings_obj = review_summary.get("findings")
    if not isinstance(findings_obj, list):
        return []

    findings = cast(list[object], findings_obj)
    out: list[InlineCandidate] = []
    for raw_item in findings:
        item = _as_mapping(raw_item)
        if not item:
            continue

        priority = _as_str(item.get("priority")).upper()
        if priority not in {"P0", "P1"}:
            continue

        title = _as_str(item.get("title"))

        code_location = _as_mapping(item.get("code_location"))
        repo_relative_path = _as_str(code_location.get("repo_relative_path"))
        start_line, end_line = _as_line_range(code_location)

        if not repo_relative_path or start_line <= 0:
            out.append(
                InlineCandidate(
                    title=title,
                    priority=priority,
                    repo_relative_path=repo_relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    diff_position=None,
                    inline_eligible=False,
                    skip_reason="invalid_code_location",
                    fingerprint=finding_fingerprint(item),
                )
            )
            continue

        diff_position = resolve_diff_position(
            line_map,
            repo_relative_path=repo_relative_path,
            line=start_line,
        )
        if diff_position is None:
            out.append(
                InlineCandidate(
                    title=title,
                    priority=priority,
                    repo_relative_path=repo_relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    diff_position=None,
                    inline_eligible=False,
                    skip_reason="line_not_mapped",
                    fingerprint=finding_fingerprint(item),
                )
            )
            continue

        out.append(
            InlineCandidate(
                title=title,
                priority=priority,
                repo_relative_path=repo_relative_path,
                start_line=start_line,
                end_line=end_line,
                diff_position=diff_position,
                inline_eligible=True,
                skip_reason="",
                fingerprint=finding_fingerprint(item),
            )
        )

    return out

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import cast


_SPACE_RE = re.compile(r"\s+")


def _as_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    mapping = cast(Mapping[object, object], value)
    out: dict[str, object] = {}
    for key_obj, mapped_value in mapping.items():
        if isinstance(key_obj, str):
            out[key_obj] = mapped_value
    return out


def _norm_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return _SPACE_RE.sub(" ", value).strip()


def _norm_priority(value: object) -> str:
    s = _norm_text(value).upper()
    if s in {"P0", "P1", "P2", "P3"}:
        return s
    return ""


def _norm_int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def finding_fingerprint(finding: Mapping[str, object]) -> str:
    code_location = _as_mapping(finding.get("code_location"))

    line_range = _as_mapping(code_location.get("line_range"))

    raw_sources = finding.get("sources")
    sources: list[str] = []
    if isinstance(raw_sources, list):
        normalized_sources = cast(list[object], raw_sources)
        seen: set[str] = set()
        for item in normalized_sources:
            src = _norm_text(item)
            if not src or src in seen:
                continue
            seen.add(src)
            sources.append(src)
    sources.sort()

    canonical = {
        "title": _norm_text(finding.get("title")),
        "body": _norm_text(finding.get("body")),
        "priority": _norm_priority(finding.get("priority")),
        "path": _norm_text(code_location.get("repo_relative_path")),
        "start": _norm_int(line_range.get("start")),
        "end": _norm_int(line_range.get("end")),
        "sources": sources,
    }

    payload = json.dumps(
        canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"k7f1:{digest}"

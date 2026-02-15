"""OpenCode output extraction.

OpenCode can emit JSON Lines (JSONL) events when run with `--format json`.
This module extracts the final text output from those events and validates it.
"""

from __future__ import annotations

import json
from typing import Any

from ..errors import ExecFailureError


def loads_jsonl_events(text: str) -> list[dict[str, Any]]:
    """Parse OpenCode JSONL output into a list of event objects.

    Notes:
    - Some builds may print non-JSON logs; those lines are ignored.
    - If a line *looks* like JSON (starts with '{') but fails to parse, this
      raises ExecFailureError.
    """

    events: list[dict[str, Any]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExecFailureError("OpenCode returned invalid JSONL event") from exc
        if isinstance(obj, dict):
            events.append(obj)

    if not events:
        raise ExecFailureError("OpenCode returned no JSON events")

    return events


def extract_last_text(events: list[dict[str, Any]]) -> str:
    """Extract the final `type=text` event's `part.text`.

    This follows the extraction pattern used in `scripts/bench-sdd-docs.py`.
    """

    last: str | None = None
    for e in events:
        if e.get("type") != "text":
            continue
        part = e.get("part") or {}
        if isinstance(part, dict):
            t = part.get("text")
            if isinstance(t, str):
                last = t

    if last is None:
        raise ExecFailureError("OpenCode JSON events contained no final text output")
    return last


def parse_json_from_text(text: str) -> Any:
    """Parse JSON from the extracted final text.

    AC2 requires treating invalid JSON as an execution failure.
    """

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExecFailureError("OpenCode returned invalid JSON") from exc


def extract_json_from_jsonl(text: str) -> Any:
    events = loads_jsonl_events(text)
    final_text = extract_last_text(events)
    return parse_json_from_text(final_text)


def extract_json_from_jsonl_lines(lines: Any) -> Any:
    """Extract final JSON from an iterable of JSONL lines.

    This variant is for large outputs to avoid loading the whole stream into
    memory before parsing.
    """

    saw_event = False
    last_text: str | None = None

    for raw in lines:
        if isinstance(raw, bytes):
            line = raw.decode("utf-8", errors="replace").strip()
        else:
            line = str(raw).strip()
        if not line:
            continue
        if not line.startswith("{"):
            continue
        saw_event = True
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExecFailureError("OpenCode returned invalid JSONL event") from exc

        if not isinstance(obj, dict):
            continue
        if obj.get("type") != "text":
            continue
        part = obj.get("part") or {}
        if not isinstance(part, dict):
            continue
        t = part.get("text")
        if isinstance(t, str):
            last_text = t

    if not saw_event:
        raise ExecFailureError("OpenCode returned no JSON events")
    if last_text is None:
        raise ExecFailureError("OpenCode JSON events contained no final text output")

    return parse_json_from_text(last_text)


def extract_json_and_tool_uses_from_jsonl_lines(
    lines: Any,
) -> tuple[Any, list[dict[str, Any]]]:
    saw_event = False
    last_text: str | None = None
    tool_uses: list[dict[str, Any]] = []

    for raw in lines:
        if isinstance(raw, bytes):
            line = raw.decode("utf-8", errors="replace").strip()
        else:
            line = str(raw).strip()
        if not line:
            continue
        if not line.startswith("{"):
            continue
        saw_event = True
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExecFailureError("OpenCode returned invalid JSONL event") from exc

        if not isinstance(obj, dict):
            continue

        if obj.get("type") == "tool_use":
            tool_uses.append(obj)
            continue

        if obj.get("type") != "text":
            continue
        part = obj.get("part") or {}
        if not isinstance(part, dict):
            continue
        t = part.get("text")
        if isinstance(t, str):
            last_text = t

    if not saw_event:
        raise ExecFailureError("OpenCode returned no JSON events")
    if last_text is None:
        raise ExecFailureError("OpenCode JSON events contained no final text output")

    return (parse_json_from_text(last_text), tool_uses)

#!/usr/bin/env python3
"""Generate SARIF fixtures for Issue #56 PoC verification.

Generates test SARIF 2.1.0 files for:
1. Category split verification (multi-priority findings)
2. Count limit verification (varying number of findings)

Each count fixture is generated in both pretty-printed (.sarif.json)
and compact (.compact.sarif.json) format.  The compact variant omits
indentation so that more results fit under GitHub's 10 MB SARIF upload
limit.

Usage:
    python scripts/poc-sarif-fixtures.py [--output-dir DIR]

Output:
    <output-dir>/category-split.sarif.json       -- 20 findings across P0/P1/P2/P3
    <output-dir>/count-NNN.sarif.json             -- pretty-printed
    <output-dir>/count-NNN.compact.sarif.json     -- compact (for upload)
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import cast

_PROJECT_URL = "https://github.com/ToaruPen/Killer-7"
_SARIF_HELP_URI = (
    "https://github.com/ToaruPen/Killer-7/blob/main/docs/operations/sarif-reviewdog.md"
)
_GITHUB_SARIF_SIZE_LIMIT_MB = 10.0
_DEFAULT_COUNT_TARGETS: tuple[int, ...] = (100, 1000, 5000, 5001, 10000, 25000, 25001)
_CATEGORY_REPEAT_COUNT = 5
_CATEGORY_PATH_STRIDE_MULTIPLIER = 2
_CATEGORY_LINE_OFFSET_BASE = 1
_CATEGORY_LINE_OFFSET_STEP = 10
_CATEGORY_PRIORITY_LINE_BLOCK = 100
_COUNT_LINE_CYCLE = 500
_COUNT_LINE_OFFSET_BASE = 1
# Priority distribution weights for count-based fixtures.
_PRIORITY_P0_WEIGHT = 0.10
_PRIORITY_P1_WEIGHT = 0.20
_PRIORITY_P2_WEIGHT = 0.40
_PRIORITY_P3_WEIGHT = 0.30

_PRIORITY_TO_LEVEL = {
    "P0": "error",
    "P1": "error",
    "P2": "warning",
    "P3": "note",
}

# Synthetic file paths for fixtures.
# Use distinct paths so GitHub UI can show location-based grouping.
_SYNTHETIC_PATHS = [
    "src/app.py",
    "src/auth/login.py",
    "src/auth/token.py",
    "src/api/routes.py",
    "src/api/middleware.py",
    "src/db/models.py",
    "src/db/queries.py",
    "src/utils/helpers.py",
    "src/utils/validators.py",
    "src/config.py",
]


def _fingerprint(title: str, path: str, start: int, priority: str) -> str:
    """Deterministic fingerprint matching Killer-7 format."""
    canonical = {
        "title": title,
        "body": f"PoC fixture finding for {priority}",
        "priority": priority,
        "path": path,
        "start": start,
        "end": start,
        "sources": [f"{path}#L{start}-L{start}"],
    }
    payload = json.dumps(
        canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"k7f1:{digest}"


def _make_rule(priority: str) -> dict[str, object]:
    """Create a SARIF rule definition for a priority level."""
    return {
        "id": f"K7.{priority}",
        "name": f"Killer-7 {priority}",
        "shortDescription": {"text": f"Killer-7 finding priority {priority}"},
        "defaultConfiguration": {"level": _PRIORITY_TO_LEVEL[priority]},
        "helpUri": _SARIF_HELP_URI,
    }


def _make_result(
    index: int,
    priority: str,
    path: str,
    start_line: int,
) -> dict[str, object]:
    """Create a single SARIF result."""
    title = f"[{priority}] Finding #{index}: review issue in {path}"
    body = f"PoC fixture finding for {priority}"
    return {
        "ruleId": f"K7.{priority}",
        "level": _PRIORITY_TO_LEVEL[priority],
        "message": {"text": f"{title}\n{body}"},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": path},
                    "region": {
                        "startLine": start_line,
                        "endLine": start_line,
                    },
                }
            }
        ],
        "partialFingerprints": {
            "k7/finding": _fingerprint(title, path, start_line, priority),
        },
        "properties": {
            "priority": priority,
            "sources": [f"{path}#L{start_line}-L{start_line}"],
            "scope_id": "poc/issue-56",
        },
    }


def _wrap_sarif(
    results: list[dict[str, object]],
    priorities: set[str],
) -> dict[str, object]:
    """Wrap results in a valid SARIF 2.1.0 envelope."""
    rules = [_make_rule(p) for p in sorted(priorities)]
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
                    "id": "killer-7/poc-issue-56",
                },
                "results": results,
            }
        ],
    }


def generate_category_split() -> dict[str, object]:
    """Generate a SARIF with findings across all 4 priority levels.

    20 findings total: 5 per priority (P0, P1, P2, P3).
    Each priority uses different synthetic file paths for visual distinction.
    """
    results: list[dict[str, object]] = []
    priorities = {"P0", "P1", "P2", "P3"}

    for priority_idx, priority in enumerate(sorted(priorities)):
        for i in range(_CATEGORY_REPEAT_COUNT):
            path_idx = (priority_idx * _CATEGORY_PATH_STRIDE_MULTIPLIER + i) % len(
                _SYNTHETIC_PATHS
            )
            path = _SYNTHETIC_PATHS[path_idx]
            start_line = (
                priority_idx * _CATEGORY_PRIORITY_LINE_BLOCK
                + i * _CATEGORY_LINE_OFFSET_STEP
                + _CATEGORY_LINE_OFFSET_BASE
            )
            results.append(
                _make_result(
                    index=priority_idx * _CATEGORY_REPEAT_COUNT + i + 1,
                    priority=priority,
                    path=path,
                    start_line=start_line,
                )
            )

    return _wrap_sarif(results, priorities)


def generate_count_fixture(count: object) -> dict[str, object]:
    """Generate a SARIF with exactly `count` findings.

    Distributes findings across priorities (P0:P1:P2:P3 = 1:2:4:3 ratio)
    and rotates through synthetic file paths.
    """
    if not isinstance(count, int):
        raise TypeError("count must be an int")
    if count < 0:
        raise ValueError("count must be non-negative")

    results: list[dict[str, object]] = []
    priorities_used: set[str] = set()

    priority_weights = [
        ("P0", _PRIORITY_P0_WEIGHT),
        ("P1", _PRIORITY_P1_WEIGHT),
        ("P2", _PRIORITY_P2_WEIGHT),
        ("P3", _PRIORITY_P3_WEIGHT),
    ]

    # Pre-compute counts per priority
    priority_counts: list[tuple[str, int]] = []
    remaining = count
    for idx, (priority, weight) in enumerate(priority_weights):
        if idx == len(priority_weights) - 1:
            n = remaining  # last priority gets remainder
        else:
            n = int(count * weight)
            remaining -= n
        priority_counts.append((priority, n))

    global_idx = 0
    for priority, n in priority_counts:
        if n <= 0:
            continue
        priorities_used.add(priority)
        for _ in range(n):
            path = _SYNTHETIC_PATHS[global_idx % len(_SYNTHETIC_PATHS)]
            start_line = (global_idx % _COUNT_LINE_CYCLE) + _COUNT_LINE_OFFSET_BASE
            results.append(
                _make_result(
                    index=global_idx + 1,
                    priority=priority,
                    path=path,
                    start_line=start_line,
                )
            )
            global_idx += 1

    return _wrap_sarif(results, priorities_used)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate SARIF fixtures for Issue #56 PoC verification"
    )
    _ = parser.add_argument(
        "--output-dir",
        default=".ai-review/poc-sarif-fixtures",
        help="Directory to write SARIF fixture files (default: .ai-review/poc-sarif-fixtures)",
    )
    args = parser.parse_args()

    output_dir = Path(cast(str, args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- category-split (pretty only) ---
    cat_sarif = generate_category_split()
    _write_and_report(output_dir, "category-split.sarif.json", cat_sarif, indent=2)

    # --- count fixtures (pretty + compact) ---
    for count in _DEFAULT_COUNT_TARGETS:
        sarif = generate_count_fixture(count)
        _write_and_report(output_dir, f"count-{count}.sarif.json", sarif, indent=2)
        _write_and_report(
            output_dir, f"count-{count}.compact.sarif.json", sarif, indent=None
        )

    print(f"\nAll fixtures written to: {output_dir}")
    return 0


def _write_and_report(
    output_dir: Path,
    filename: str,
    sarif: dict[str, object],
    *,
    indent: int | None,
) -> None:
    """Write a SARIF file and print size metrics."""
    filepath = output_dir / filename
    separators = (",", ":") if indent is None else (", ", ": ")

    runs = cast(list[object], sarif.get("runs", []))
    if not runs or not isinstance(runs[0], dict):
        raise ValueError("Invalid SARIF shape: missing runs[0]")
    run0 = cast(dict[str, object], runs[0])
    if "results" not in run0:
        raise ValueError(f"Invalid SARIF shape: missing runs[0].results ({run0!r})")
    results = cast(list[object], run0["results"])

    content = json.dumps(
        sarif, indent=indent, ensure_ascii=False, separators=separators
    )
    raw_bytes = (content + "\n").encode("utf-8")
    _ = filepath.write_bytes(raw_bytes)
    result_count = len(results)
    size_mb = len(raw_bytes) / (1024 * 1024)
    gz_size = len(gzip.compress(raw_bytes, compresslevel=6))
    gz_mb = gz_size / (1024 * 1024)
    flag = " *** >10 MB" if gz_mb > _GITHUB_SARIF_SIZE_LIMIT_MB else ""
    print(
        f"  {filename}: {result_count} results, {size_mb:.2f} MB (gzip {gz_mb:.2f} MB){flag}"
    )


if __name__ == "__main__":
    raise SystemExit(main())

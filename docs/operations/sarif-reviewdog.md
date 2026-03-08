# Killer-7 SARIF / reviewdog Integration Guide

## Overview

This guide explains how to use `--sarif` and `--reviewdog` with Killer-7 so review results can be consumed as SARIF and surfaced as PR annotations.

Design intent:
- Keep native inline comments (`--inline`) as the default path
- Treat SARIF and reviewdog as opt-in integration paths

## Prerequisites

- `killer-7 review` is available in the execution environment
- `gh` is authenticated for the target repository
- `reviewdog` is installed if you want reviewdog-based annotations

## Local Usage

### Generate SARIF only

```bash
killer-7 review --repo owner/name --pr 123 --sarif
```

Generated files:
- `.ai-review/review-summary.json`
- `.ai-review/review-summary.md`
- `.ai-review/review-summary.sarif.json`

### Add reviewdog annotations

```bash
killer-7 review --repo owner/name --pr 123 --sarif --reviewdog --reviewdog-reporter github-pr-review
```

Notes:
- `--reviewdog` automatically implies SARIF generation
- `KILLER7_REVIEWDOG_TIMEOUT_S` can be set to a positive integer to change the reviewdog timeout

## GitHub Actions Examples

### 1. Upload SARIF to Code Scanning

```yaml
- name: Run Killer-7 review (SARIF)
  run: |
    killer-7 review --repo "$GITHUB_REPOSITORY" --pr "${{ github.event.pull_request.number }}" --sarif

- name: Upload SARIF
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: .ai-review/review-summary.sarif.json
```

### 2. Add reviewdog PR annotations

```yaml
- name: Run Killer-7 review with reviewdog
  env:
    REVIEWDOG_GITHUB_API_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    killer-7 review --repo "$GITHUB_REPOSITORY" --pr "${{ github.event.pull_request.number }}" --sarif --reviewdog --reviewdog-reporter github-pr-review
```

## Operational Notes

- `--reviewdog` is supplementary. Quality-gate decisions should still follow review summary, evidence validation, and inline posting rules.
- If Killer-7 detects a stale head SHA, it fails fast, clears stale artifacts, and requires a rerun.
- If a run does not use `--sarif` or `--reviewdog`, stale `review-summary.sarif.json` is deleted automatically.

## basedpyright Rollout

- `[tool.basedpyright]` in `pyproject.toml` explicitly keeps `reportAny`, `reportExplicitAny`, and `reportUnusedCallResult` at warning level for gradual adoption
- The SARIF / inline path cleanup from Issue #62 should be expanded in later passes until warnings are reduced further

## GitHub Code Scanning Limits (Measured in PoC #56)

Measured on 2026-02-25. Details: `docs/poc/issue-56-sarif-display.md`

### File Size

- Limit: **10 MB** after compression handling by GitHub upload rules
- An uncompressed 11.24 MB SARIF file still uploaded successfully after gzip to 1.40 MB
- Normal Killer-7 usage with tens to hundreds of findings is very unlikely to hit the size limit

### Result Count Limits

| Limit | Value | Behavior When Exceeded |
|---|---|---|
| Display limit per analysis | **5,000** | Silent truncation (highest severity wins) |
| Hard limit per run | **25,000** | Explicit rejection |

Observed behavior:
- Uploads with 5,001+ results still returned `processing_status: "complete"` with no API error
- Only the highest-priority 5,000 results were retained
- This truncation is easy to miss, so Killer-7 implements guardrails

### Killer-7 Guardrails

- For **5,001 to 25,000** findings, Killer-7 writes `sarif_result_limit_warning` to `warnings.txt`
- For **25,001+** findings, Killer-7 fails fast and does not emit SARIF

### Category Handling

- SARIF containing multiple `ruleId` values such as `K7.P0`, `K7.P1`, `K7.P2`, and `K7.P3` is processed correctly
- Severity-based filtering works as expected (`error`, `warning`, `note`)
- `automationDetails.id` is used as the Code Scanning category

## LSP Warning Cleanup Phases (Issue #59)

### Phase 1 Results

- Scope: `killer_7/report/sarif_export.py`, `killer_7/cli.py`
- `reportImplicitStringConcatenation`: **29 -> 0**
- `reportUnknown*`: **80 -> 10**
- `killer_7/report/sarif_export.py`: **11 -> 0** warnings
- `killer_7/cli.py`: **217 -> 130** warnings

### Phase 2 Priorities

1. Reduce `reportAny` / `reportExplicitAny` in `killer_7/cli.py`
2. Reduce `reportUnusedCallResult` in `killer_7/cli.py`
3. Clean up test-only warnings in `tests/test_cli.py` and `tests/test_sarif_export.py`
4. Refine `[tool.basedpyright]` thresholds in `pyproject.toml`

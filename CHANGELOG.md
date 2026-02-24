# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- Added `--aspect` and `--preset` to `killer-7 review` to opt into a subset of review aspects.
- Added persisted review state (`.ai-review/state.json`) and incremental diff mode based on previous `head_sha`.
- Added `--full` to force full PR diff review and `--no-sot-aspect` to disable SoT injection per aspect.
- Added `--reuse` / `--no-reuse` to `killer-7 review`, plus `.ai-review/cache.json` metadata for safe artifact reuse decisions.
- Added `scripts/killer-7-update.sh` for tag-based update operations with `stable`/`canary` channels and healthcheck rollback.
- Added `docs/operations/killer-7-update.md` to document deployment/update/rollback procedures for managed PCs.
- Added Decision Snapshot `D-2026-02-22-KILLER7_TAG_CHANNEL_AUTO_UPDATE` and synced PRD/Epic entries for update infrastructure.
- Added event-driven Codex review detection via `.github/workflows/codex-review-events.yml` and `scripts/codex-review-event.sh`.
- Added SARIF/reviewdog integration for `killer-7 review`: `--sarif`, `--reviewdog`, and `--reviewdog-reporter`.
- Added `docs/operations/sarif-reviewdog.md` with reproducible GitHub Actions linkage examples (`upload-sarif` and reviewdog annotation flow).

### Changed
- Improved `killer-7 review --help` examples and validation around aspect selection.
- Updated inline comment posting to use full PR diff when review runs in incremental mode.
- Extended PR input metadata (`meta.json`) with `diff_mode` and `base_head_sha`.
- Reuse now validates scope, selected aspects, prompt hashes, and execution parameters, and fails fast when cached artifacts are missing/invalid.
- Synced Agentic-SDD managed assets to `v0.3.08` (commands, review-cycle flow, lint-sot, and related tests).
- Cleaned variable naming in CLI/OpenCode runner paths and aligned tests/scripts with S603-safe subprocess usage and Python executable resolution.
- Updated `.github/workflows/release.yml` to publish Killer-7 Docker images to GHCR with version tags and `latest` on tag releases.
- Added timeout control and explicit timeout failure handling to reviewdog execution (`KILLER7_REVIEWDOG_TIMEOUT_S`) to avoid indefinite hangs.

## [0.1.1] - 2026-02-11

### Changed
- Removed the "開発状況" section from `README.md`.

## [0.1.0] - 2026-02-11

### Added
- Added `CHANGELOG.md` to track project-level changes.

### Changed
- Updated `README.md` development status to reflect the current implementation state and operational workflow.

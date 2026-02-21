# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- Added `--aspect` and `--preset` to `killer-7 review` to opt into a subset of review aspects.
- Added persisted review state (`.ai-review/state.json`) and incremental diff mode based on previous `head_sha`.
- Added `--full` to force full PR diff review and `--no-sot-aspect` to disable SoT injection per aspect.

### Changed
- Improved `killer-7 review --help` examples and validation around aspect selection.
- Updated inline comment posting to use full PR diff when review runs in incremental mode.
- Extended PR input metadata (`meta.json`) with `diff_mode` and `base_head_sha`.
- Synced Agentic-SDD managed assets to `v0.3.08` (commands, review-cycle flow, lint-sot, and related tests).

## [0.1.1] - 2026-02-11

### Changed
- Removed the "開発状況" section from `README.md`.

## [0.1.0] - 2026-02-11

### Added
- Added `CHANGELOG.md` to track project-level changes.

### Changed
- Updated `README.md` development status to reflect the current implementation state and operational workflow.

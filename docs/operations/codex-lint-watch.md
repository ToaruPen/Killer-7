# Codex Save-Time Ruff Watch

## Overview

Codex CLI does not currently expose a repository-local hook that runs after each file write.
For Killer-7, use the repo-local watcher script instead. It polls the working tree and runs Ruff after saves in `killer_7/`, `tests/`, or `scripts/`.

This watcher complements the existing Git hooks in `.githooks/`:
- save-time feedback: `scripts/codex-watch-lint.py`
- commit/push enforcement: `.githooks/pre-commit`, `.githooks/pre-push`

## What It Checks

- A changed Python file in `killer_7/`, `tests/`, or `scripts/`:
  - `ruff check <changed-file>`
  - `ruff format --check <changed-file>`
- A change to `pyproject.toml`, `requirements-dev.txt`, or `requirements-killer7.txt`:
  - `ruff check killer_7 tests scripts`
  - `ruff format --check killer_7 tests scripts`
- A deletion of any watched Python file:
  - run the full repo-wide Ruff checks to catch fallout from removed imports or moved modules

Fail-fast behavior is preserved:
- if `ruff` is unavailable, the watcher exits immediately with an explicit install command
- if Ruff reports violations, the watcher prints the failing exit code and keeps watching for the next save

## Usage

From the repository root:

```bash
.venv/bin/python scripts/codex-watch-lint.py
```

Optional flags:

```bash
.venv/bin/python scripts/codex-watch-lint.py --interval 0.5
.venv/bin/python scripts/codex-watch-lint.py --once
```

Typical workflow:
1. Start Codex in one terminal pane.
2. Start `scripts/codex-watch-lint.py` in another pane.
3. Edit files as usual and watch Ruff output after each save.

## Scope Limits

- The watcher is intentionally limited to Ruff because Ruff is the repository's defined lint/format gate.
- It does not run `unittest` on every save.
- It does not lint shell scripts; shell changes remain covered by the existing script-specific test flow and Git hooks.

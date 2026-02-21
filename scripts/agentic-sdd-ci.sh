#!/usr/bin/env bash

set -euo pipefail

eprint() { printf '%s\n' "$*" >&2; }

run_cmd() {
  local name="$1"
  local cmd="$2"

  eprint "[CI] $name: $cmd"
  bash -lc "$cmd"
}

test_cmd="${AGENTIC_SDD_CI_TEST_CMD:-}"
lint_cmd="${AGENTIC_SDD_CI_LINT_CMD:-}"
typecheck_cmd="${AGENTIC_SDD_CI_TYPECHECK_CMD:-}"
docs_cmd="${AGENTIC_SDD_CI_DOCS_CMD:-}"

missing=()
[[ -n "$test_cmd" ]] || missing+=("AGENTIC_SDD_CI_TEST_CMD")
[[ -n "$lint_cmd" ]] || missing+=("AGENTIC_SDD_CI_LINT_CMD")
[[ -n "$typecheck_cmd" ]] || missing+=("AGENTIC_SDD_CI_TYPECHECK_CMD")

if [[ "${#missing[@]}" -gt 0 ]]; then
  eprint "[CI] Missing CI command configuration: ${missing[*]}"
  eprint "Set AGENTIC_SDD_CI_TEST_CMD / AGENTIC_SDD_CI_LINT_CMD / AGENTIC_SDD_CI_TYPECHECK_CMD in workflow env."
  exit 1
fi

run_cmd "tests" "$test_cmd"
run_cmd "lint" "$lint_cmd"
run_cmd "typecheck" "$typecheck_cmd"

if [[ -n "$docs_cmd" ]]; then
  run_cmd "docs" "$docs_cmd"
fi

eprint "[CI] OK"

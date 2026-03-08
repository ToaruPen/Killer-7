# Killer-7

Killer-7 is a local CLI that takes a GitHub PR as input, runs multi-aspect LLM review, and produces reports plus optional PR comments (summary and inline) through Docker-based execution.

## Purpose

- Reduce LLM quota consumption during development while preventing LLM-driven code degradation or project breakage
- Use diff + Context Bundle + SoT allowlist with schema/evidence validation to suppress claims that lack strong grounding

## Testing

Python 3.11:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install -r requirements-killer7.txt

.venv/bin/python -m unittest discover -s tests -p 'test*.py'
.venv/bin/ruff check killer_7 tests scripts
.venv/bin/ruff format --check killer_7 tests scripts
```

Save-time Ruff feedback while using Codex:

```bash
.venv/bin/python scripts/codex-watch-lint.py
```

## Artifacts

- Output root: `./.ai-review/`
- Minimal run metadata: `./.ai-review/run.json`
- PR input:
  - `./.ai-review/diff.patch`
  - `./.ai-review/changed-files.tsv`
  - `./.ai-review/meta.json`

- Evidence validation:
  - `./.ai-review/evidence.json`
  - `./.ai-review/aspects/<aspect>.raw.json`
  - `./.ai-review/aspects/<aspect>.evidence.json`
  - `./.ai-review/aspects/<aspect>.policy.json`
  - `./.ai-review/aspects/index.evidence.json`
  - `./.ai-review/aspects/index.policy.json`

## Exit Codes

- `0`: success
- `1`: blocked, with missing prerequisites or required user action
- `2`: execution failure, such as invalid input or runtime error

## Docker

```bash
docker build -t killer-7 .

docker run --rm -u "$(id -u):$(id -g)" -v "$PWD":/work -w /work killer-7 \
  review --repo owner/name --pr 123
```

## Usage

```bash
# Review a PR without posting comments
killer-7 review --repo owner/name --pr 123

# Run a reduced set of aspects
killer-7 review --repo owner/name --pr 123 --aspect correctness
killer-7 review --repo owner/name --pr 123 --aspect correctness --aspect security

# Run the full preset
killer-7 review --repo owner/name --pr 123 --preset full

# Post a summary comment
killer-7 review --repo owner/name --pr 123 --post

# Post summary plus inline comments for P0/P1
killer-7 review --repo owner/name --pr 123 --post --inline

# Explore mode
killer-7 review --repo owner/name --pr 123 --explore
```

Notes:

- The expected execution model is Docker, with artifacts stored under `./.ai-review/`
- By default the tool sends only diff + Context Bundle + SoT to the LLM, and allows extra repo context only through read-only path allowlists
- The default SoT allowlist is `README.md`, `CHANGELOG.md`, and `docs/**/*.md`
- See `killer-7 review --help` for the full option set

Explore mode (`--explore`):

- OpenCode may inspect the repo with read plus read-only `git` commands to gather missing context
- Tool traces are persisted under `.ai-review/` so evidence validation can treat explored context as grounded input
- Bash is restricted to read-only `git` commands; unsupported commands or missing required flags are blocked with exit code `1`
- Reads are limited to tracked repo files, and sensitive areas such as `.git/` and `.ai-review/` are denied
- Policy is enforced after the run against the recorded JSONL tool trace; this is validation of behavior, not a full process sandbox
- Limits can be tuned with environment variables such as `KILLER7_EXPLORE_MAX_STDOUT_JSONL_BYTES`, `KILLER7_EXPLORE_MAX_TOOL_CALLS`, `KILLER7_EXPLORE_MAX_BASH_CALLS`, `KILLER7_EXPLORE_MAX_READ_LINES`, `KILLER7_EXPLORE_MAX_FILES`, and `KILLER7_EXPLORE_MAX_BUNDLE_BYTES`

Additional artifacts:

- `./.ai-review/tool-trace.jsonl`
- `./.ai-review/tool-bundle.txt` for read paths, line numbers, and excerpts with sensitive data redacted
- `./.ai-review/opencode/<aspect-*>/stdout.jsonl` for redacted JSONL events with tool outputs stripped

## Operational Docs

- Update and rollback flow: `docs/operations/killer-7-update.md`
- SARIF and reviewdog integration: `docs/operations/sarif-reviewdog.md`
- Save-time Ruff watcher for Codex sessions: `docs/operations/codex-lint-watch.md`

# AGENTS.md

This repository is for Killer-7 itself. Do not assume any legacy workflow bundle, custom command set, or generated control assets are present.

## Communication

- Respond to the user in English unless they ask otherwise.
- Base decisions on files or command output observed in this repo.
- Report what you changed and which checks you actually ran.

## Working Style

- Prefer the smallest change that removes the problem without weakening behavior.
- Preserve fail-fast behavior. Do not add silent fallbacks.
- Keep Killer-7 application code, tests, and operational docs consistent.

## Primary References

- Product overview: `README.md`
- Operational docs: `docs/operations/`
- PoC / validation notes: `docs/poc/`
- Default SoT allowlist: `killer_7/sot/allowlist.py`

## Validation

- Unit tests: `python3 -m unittest discover -s tests -p 'test*.py'`
- Ruff: `ruff check killer_7 tests scripts`
- Ruff format check: `ruff format --check killer_7 tests scripts`
- If you change a shell script, also run the relevant `scripts/tests/test-*.sh`

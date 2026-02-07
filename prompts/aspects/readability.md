## Readability Focus Areas

- Naming clarity: intention-revealing names; consistent terminology.
- Structure: keep responsibilities small; reduce nesting where possible.
- Comments/docstrings: request only when the changed API is public or the logic is non-obvious.
- Magic numbers: only flag domain-specific or repeated literals that should be named.

## Readability-Specific Priority Guidelines

- P0: so unclear it could lead to bugs during maintenance
- P1: significant readability issue that will slow down development
- P2: understandable but could be clearer
- P3: small naming or documentation suggestion

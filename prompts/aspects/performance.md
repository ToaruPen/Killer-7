## Performance Focus Areas

- Obvious O(n^2) or worse behavior where a simpler approach exists.
- Unnecessary I/O or repeated expensive work.
- Inefficient regex patterns or repeated parsing/serialization.

When reporting a complexity issue, quote the relevant loop nesting/repeated calls and explain the Big-O in 1 sentence.

## Performance-Specific Priority Guidelines

- P0: will cause severe degradation or outage under expected usage
- P1: significant performance issue likely to affect users
- P2: acceptable but improvable
- P3: minor optimization opportunity

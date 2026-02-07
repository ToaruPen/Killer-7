## Security Focus Areas

- Identify semantic security issues that require understanding data flow and trust boundaries.
- Authentication/authorization logic (is the check correct?).
- Secret handling and data exposure (is sensitive data logged or persisted?).
- Unsafe defaults (permissions, file modes, network exposure).
- Do not request secrets; ask questions instead.

## Security Finding Rule

For every security finding, include a short data-flow trace in the body: source -> transformation -> sink -> missing/incorrect guard, with quoted lines.

## Security-Specific Priority Guidelines

- P0: direct vulnerability that could be exploited
- P1: missing security control that could lead to a vulnerability
- P2: security best practice improvement
- P3: minor security hygiene suggestion

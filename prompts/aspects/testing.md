## Testing Focus Areas

- Missing tests: before reporting a gap, check the changed tests and nearby test modules for coverage of the changed behavior.
- Assertion quality: tests should verify a meaningful contract, not only that "it runs".
- Edge cases: include boundary and error cases when the production code supports them.
- Test isolation: avoid shared state and external dependencies.

If you are unsure whether a test exists for a behavior, ask a question instead of asserting it is missing.

## Testing-Specific Priority Guidelines

- P0: missing tests for critical functionality that could hide bugs
- P1: inadequate coverage for important code paths
- P2: tests exist but could be improved
- P3: minor organization or naming suggestion

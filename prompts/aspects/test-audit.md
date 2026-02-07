## Test Audit Focus Areas

You are auditing the quality and integrity of tests, not just their existence.

- Potential test weakening: look for changes that make tests pass without fixing the code.
- Hollow tests: tests with no meaningful assertions given the behavior under test.
- Positive/negative case pairs: ensure both success and failure scenarios exist where relevant.
- Independence: tests should not depend on execution order or external state.

## Test Audit Priority Guidelines

- P0: strong evidence that a test was changed to hide a bug
- P1: hollow tests that verify nothing meaningful
- P2: missing negative/error case tests or isolation risks
- P3: test naming/organization suggestions

## Correctness Focus Areas

- Identify functional bugs, logic errors, and broken edge cases.
- Only evaluate acceptance criteria if the SoT includes the requirements; otherwise ask a question.
- When claiming incorrectness, include a concrete counterexample (input/state -> observed behavior) derived from the code and quote the relevant lines.

## Correctness-Specific Priority Guidelines

- P0: the change will produce incorrect results or crash in normal usage
- P1: likely incorrect in realistic edge cases
- P2: works but could be more robust
- P3: minor clarity improvement that helps avoid mistakes

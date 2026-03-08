---
name: UI Iteration
about: Iterate on UI improvements in short rounds
title: "feat(ui): improve <screen>"
labels: ["enhancement", "ui"]
assignees: []
---

## Summary

<!-- Describe what should improve in 1-2 sentences -->

## Reference Docs

- Main reference: <!-- e.g. README.md or docs/operations/... -->
- Supporting reference: <!-- optional -->

## Target Screen / Route

- Screen: <!-- e.g. KIOSK -->
- Route: <!-- e.g. /kiosk -->

## Current Problems (ordered by priority)

### P0 / P1

- [ ] <!-- e.g. The main button appears enabled during an error state -->

### P2

- [ ] <!-- e.g. A CTA overlays important content -->

### P3

- [ ] <!-- e.g. Copy inconsistency or small spacing issue -->

## Acceptance Criteria

- [ ] Interaction state and visual state do not contradict each other
- [ ] Primary actions are easy to reach on desktop and mobile
- [ ] CTAs do not cover key content
- [ ] Debug-only information is not always visible in normal usage
- [ ] Standard project quality checks pass

## Non-Scope

- [ ] Backend behavior changes
- [ ] New features that are not required for this UI improvement

## Iteration Plan

- max-rounds: <!-- e.g. 3 -->
- viewports: desktop + mobile
- screenshot root: `var/screenshot/issue-<n>/round-<xx>/`

### Round Plan

- [ ] Round 00: capture the baseline
- [ ] Round 01: resolve P0/P1 issues
- [ ] Round 02: improve layout and hierarchy
- [ ] Round 03: refine copy and polish

## Verification Commands

```bash
# project standard checks (replace with your project commands)
<typecheck-command>
<lint-command>
<test-command>

# runtime / e2e as needed
<smoke-or-e2e-command>
```

## Screenshots

- Round 00:
  - desktop: <!-- var/screenshot/issue-<n>/round-00/... -->
  - mobile: <!-- var/screenshot/issue-<n>/round-00/... -->
- Round 01:
  - desktop:
  - mobile:

## Completion Checklist

- [ ] Acceptance criteria are met
- [ ] No P0/P1 issues remain
- [ ] The checks listed above are complete

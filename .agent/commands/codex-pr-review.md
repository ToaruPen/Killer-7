# /codex-pr-review

Request and iterate on Codex review for a GitHub PR using `@codex review`.

This command defines a repeatable loop:

1. Request Codex review on PR creation (or after pushing updates).
2. Fetch Codex feedback (timeline comments + inline review comments).
3. Apply fixes, verify, push.
4. Re-request review until no actionable findings remain.

Notes:

- This does not replace `/review` (final gate).
- User-facing output remains in Japanese.

## Usage

```
/codex-pr-review <PR-number | PR-url>
```

## Flow

### Phase 0: Preconditions (fail-fast)

Required:

1. The PR exists and is accessible via `gh`.
2. The Codex bot is installed/available for the repository (otherwise `@codex review` will not respond).

### Phase 1: Request Codex review (always)

After the PR is created (and the branch is pushed), comment:

```bash
gh pr comment <PR_NUMBER_OR_URL> --body "$(cat <<'EOF'
@codex review

Please review the entire PR as a diff from the base branch (main), not a single commit.

Focus on the current PR state (head SHA: <HEAD_SHA>).
Review all files changed in the PR and any relevant surrounding context.
Call out only actionable issues; avoid repeating already-fixed items.
EOF
)"
```

Notes:

- Use exactly `@codex review` (this is what the Codex bot suggests).
- If the PR is a draft, request review after marking it ready.

### Phase 2: Fetch Codex feedback

Codex may post:

- a conversation comment (PR timeline)
- a review comment attached to a file/line

Fetch both:

```bash
# Conversation comments (PR timeline)
gh api repos/<OWNER>/<REPO>/issues/<PR_NUMBER>/comments \
  --jq '.[] | select(.user.login=="chatgpt-codex-connector[bot]") | {created_at, body}'

# Inline review comments
gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/comments \
  --jq '.[] | select(.user.login=="chatgpt-codex-connector[bot]") | {created_at, path, line, body}'

# Reviews summary
gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/reviews \
  --jq '.[] | select(.user.login=="chatgpt-codex-connector[bot]") | {submitted_at, state, body}'
```

If `gh pr view <PR> --comments` is sufficient, you can use it for a quick scan.

Optional: wait for Codex to respond (polling)

```bash
PR=<PR_NUMBER>
OWNER=<OWNER>
REPO=<REPO>

while true; do
  echo "--- $(date -Iseconds)"
  gh api "repos/${OWNER}/${REPO}/issues/${PR}/comments" \
    --jq '.[] | select(.user.login=="chatgpt-codex-connector[bot]") | {created_at, body}'
  gh api "repos/${OWNER}/${REPO}/pulls/${PR}/comments" \
    --jq '.[] | select(.user.login=="chatgpt-codex-connector[bot]") | {created_at, path, line, body}'
  sleep 30
done
```

### Phase 3: Apply fixes and verify

- Only fix issues introduced by the PR.
- Keep changes minimal; avoid opportunistic refactors.
- Run the repo's standard checks before pushing.

### Phase 4: Push and re-request review

After pushing fixes:

```bash
git push
gh pr comment <PR_NUMBER_OR_URL> --body "$(cat <<'EOF'
@codex review

Please re-review the PR as a diff from the base branch (main), focusing on the current head SHA (<HEAD_SHA>).

Only call out actionable issues that remain in the current PR state; avoid repeating already-fixed items.
EOF
)"
```

### Phase 5: Output

Report (Japanese):

- The PR number/URL
- A short summary of Codex actionable findings (and what you changed)
- How you verified the changes (commands/logs)

## Exit condition

Stop when:

- Codex provides no further actionable findings
- CI is green
- human review requirements (if any) are satisfied

## Related

- `.agent/commands/review.md` - review taxonomy (status/priority) and human-readable review output
- `.agent/commands/create-pr.md` - PR creation workflow

## Next command

After addressing Codex feedback, run `/review <pr-number>` as the final gate before merge.

#!/bin/bash
# Upload a SARIF file to GitHub Code Scanning API.
# Usage: scripts/poc-sarif-upload.sh <sarif-file> [category]
# Requires: gh (authenticated), python3
set -euo pipefail

SARIF_FILE="${1:?Usage: $0 <sarif-file> [category]}"
CATEGORY="${2:-poc-issue-56}"
REPO="${GITHUB_REPOSITORY:-}"
if [ -z "$REPO" ]; then
  REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"
fi
if [ -z "$REPO" ]; then
  echo "ERROR: Repository is not resolved." >&2
  echo "       Set GITHUB_REPOSITORY or configure gh auth/repo context." >&2
  exit 1
fi
CURRENT_BRANCH="$(git branch --show-current)"
if [ -z "$CURRENT_BRANCH" ]; then
  echo "ERROR: Current branch is not available (detached HEAD)." >&2
  echo "       Check out a branch and retry." >&2
  exit 1
fi
REF="refs/heads/${CURRENT_BRANCH}"
COMMIT_SHA="$(git rev-parse HEAD)"

if [ ! -f "$SARIF_FILE" ]; then
  echo "ERROR: File not found: $SARIF_FILE" >&2
  exit 1
fi

FILE_SIZE=$(wc -c < "$SARIF_FILE" | tr -d ' ')
FILE_SIZE_MB="$(python3 -c 'import sys; print(f"{int(sys.argv[1]) / 1048576:.2f}")' "$FILE_SIZE")"
echo "File: $SARIF_FILE"
echo "Size: ${FILE_SIZE_MB} MB (${FILE_SIZE} bytes)"
echo "Category: $CATEGORY"
echo "Ref: $REF"
echo "Commit: $COMMIT_SHA"
echo ""

# Build JSON payload entirely in Python (avoids shell ARG_MAX limits).
TMPDIR_UPLOAD=$(mktemp -d)
trap 'rm -rf "$TMPDIR_UPLOAD"' EXIT
PAYLOAD_FILE="${TMPDIR_UPLOAD}/payload.json"

python3 - "$SARIF_FILE" "$COMMIT_SHA" "$REF" "$CATEGORY" "$PAYLOAD_FILE" <<'PYEOF'
import base64, gzip, json, sys

sarif_path, commit_sha, ref, category, out_path = sys.argv[1:6]

with open(sarif_path, "rb") as f:
    raw = f.read()

compressed = gzip.compress(raw, compresslevel=6)
sarif_b64 = base64.b64encode(compressed).decode("ascii")

print(f"Compressed size: {len(compressed)} bytes")

payload = {
    "commit_sha": commit_sha,
    "ref": ref,
    "sarif": sarif_b64,
    "tool_name": f"Killer-7 (PoC {category})",
}
with open(out_path, "w") as f:
    json.dump(payload, f)
PYEOF

echo "Uploading..."

RESPONSE=$(gh api \
  "repos/${REPO}/code-scanning/sarifs" \
  --method POST \
  --input "$PAYLOAD_FILE" \
  2>&1) || {
  echo "UPLOAD FAILED"
  echo "Response: $RESPONSE"
  exit 2
}

echo "UPLOAD SUCCESS"
echo "Response: $RESPONSE"

from __future__ import annotations

import unittest
from pathlib import Path


class TestPocSarifUploadScript(unittest.TestCase):
    def test_ref_uses_current_branch(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "poc-sarif-upload.sh"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn('CURRENT_BRANCH="$(git branch --show-current)"', content)
        self.assertIn('REF="refs/heads/${CURRENT_BRANCH}"', content)
        self.assertNotIn(
            'REF="refs/heads/feature/issue-56-poc-sarif-display-verification"',
            content,
        )

    def test_repo_is_resolved_dynamically(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "poc-sarif-upload.sh"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn('REPO="${GITHUB_REPOSITORY:-}"', content)
        self.assertIn(
            'REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"',
            content,
        )
        self.assertNotIn('REPO="ToaruPen/Killer-7"', content)

    def test_file_size_mb_does_not_use_bc(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "poc-sarif-upload.sh"
        content = script_path.read_text(encoding="utf-8")

        self.assertNotIn("| bc", content)
        self.assertIn('FILE_SIZE_MB="$(python3 -c', content)


if __name__ == "__main__":
    raise SystemExit(unittest.main())

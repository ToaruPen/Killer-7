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


if __name__ == "__main__":
    raise SystemExit(unittest.main())

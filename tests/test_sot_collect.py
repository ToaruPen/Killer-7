from __future__ import annotations

import unittest


class TestSotCollect(unittest.TestCase):
    def test_build_sot_markdown_truncates_to_max_lines_and_warns(self) -> None:
        from killer_7.sot.collect import build_sot_markdown

        contents_by_path = {
            "b.md": ("b\n" * 200).rstrip("\n"),
            "a.md": ("a\n" * 200).rstrip("\n"),
        }

        text, warnings = build_sot_markdown(contents_by_path, max_lines=250)

        self.assertLessEqual(len(text.splitlines()), 250)
        self.assertTrue(any("trunc" in w for w in warnings))

        # Deterministic ordering: paths should be sorted.
        self.assertLess(text.find("# SRC: a.md"), text.find("# SRC: b.md"))

        # SoT body is line-prefixed (avoids ambiguity with `# SRC:` headers).
        self.assertIn("# SRC: a.md\nL1: a\n", text)


if __name__ == "__main__":
    raise SystemExit(unittest.main())

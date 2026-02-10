from __future__ import annotations

import unittest


class TestParseContextBundle(unittest.TestCase):
    def test_indexes_src_paths_and_line_numbers(self) -> None:
        from killer_7.validate.evidence import parse_context_bundle_index

        text = "".join(
            [
                "# SRC: a.txt\n",
                "L1: hello\n",
                "L2: world\n",
                "# SRC: b.txt\n",
                "L10: foo\n",
                "# SoT Bundle\n",
                "# SRC: docs/prd/killer-7.md\n",
                "## Title\n",
            ]
        )

        idx = parse_context_bundle_index(text)
        self.assertEqual(idx["a.txt"], {1, 2})
        self.assertEqual(idx["b.txt"], {10})
        # SoT content may not include L<line>: markers; we still index the SRC header.
        self.assertIn("docs/prd/killer-7.md", idx)
        self.assertEqual(idx["docs/prd/killer-7.md"], {1})

    def test_ignores_lines_outside_src_blocks(self) -> None:
        from killer_7.validate.evidence import parse_context_bundle_index

        text = "".join(
            [
                "L1: should-not-count\n",
                "# SRC: a.txt\n",
                "L2: ok\n",
            ]
        )

        idx = parse_context_bundle_index(text)
        self.assertEqual(idx, {"a.txt": {2}})


if __name__ == "__main__":
    raise SystemExit(unittest.main())

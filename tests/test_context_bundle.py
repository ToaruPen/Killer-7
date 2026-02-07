from __future__ import annotations

import unittest


class TestContextBundle(unittest.TestCase):
    def test_builds_bundle_by_concatenating_src_blocks(self) -> None:
        from killer_7.bundle.context_bundle import build_context_bundle
        from killer_7.bundle.diff_parse import SrcBlock, SrcLine

        blocks = [
            SrcBlock(
                path="a.txt",
                lines=(
                    SrcLine(new_line=1, text="hello"),
                    SrcLine(new_line=2, text="world"),
                ),
            ),
            SrcBlock(
                path="b.txt",
                lines=(SrcLine(new_line=10, text="foo"),),
            ),
        ]

        bundle, warnings = build_context_bundle(
            blocks,
            max_total_lines=1500,
            max_file_lines=400,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            bundle,
            "".join(
                [
                    "# SRC: a.txt\n",
                    "L1: hello\n",
                    "L2: world\n",
                    "# SRC: b.txt\n",
                    "L10: foo\n",
                ]
            ),
        )

    def test_enforces_per_file_limit_without_cutting_inside_block(self) -> None:
        from killer_7.bundle.context_bundle import build_context_bundle
        from killer_7.bundle.diff_parse import SrcBlock, SrcLine

        block = SrcBlock(
            path="big.txt",
            lines=tuple(SrcLine(new_line=i, text=f"line-{i}") for i in range(1, 5)),
        )

        # block lines = 1 header + 4 content = 5 lines
        bundle, warnings = build_context_bundle(
            [block],
            max_total_lines=1500,
            max_file_lines=4,
        )

        self.assertEqual(bundle, "")
        self.assertTrue(
            any(
                "context_bundle_file_truncated" in w
                and "path=big.txt" in w
                and "limit_lines=4" in w
                for w in warnings
            )
        )

    def test_enforces_total_limit_without_cutting_inside_block(self) -> None:
        from killer_7.bundle.context_bundle import build_context_bundle
        from killer_7.bundle.diff_parse import SrcBlock, SrcLine

        a = SrcBlock(
            path="a.txt",
            lines=(
                SrcLine(new_line=1, text="a1"),
                SrcLine(new_line=2, text="a2"),
            ),
        )
        b = SrcBlock(
            path="b.txt",
            lines=(
                SrcLine(new_line=1, text="b1"),
                SrcLine(new_line=2, text="b2"),
            ),
        )

        # Each block contributes 1 header + 2 content = 3 lines.
        bundle, warnings = build_context_bundle(
            [a, b],
            max_total_lines=5,
            max_file_lines=400,
        )

        self.assertIn("# SRC: a.txt\n", bundle)
        self.assertIn("L1: a1\n", bundle)
        self.assertIn("L2: a2\n", bundle)
        self.assertNotIn("# SRC: b.txt\n", bundle)
        self.assertTrue(
            any(
                "context_bundle_total_truncated" in w and "limit_lines=5" in w
                for w in warnings
            )
        )

    def test_total_limit_can_skip_oversized_block_and_include_later_one(self) -> None:
        from killer_7.bundle.context_bundle import build_context_bundle
        from killer_7.bundle.diff_parse import SrcBlock, SrcLine

        big = SrcBlock(
            path="big.txt",
            lines=(
                SrcLine(new_line=1, text="x1"),
                SrcLine(new_line=2, text="x2"),
                SrcLine(new_line=3, text="x3"),
                SrcLine(new_line=4, text="x4"),
            ),
        )
        small = SrcBlock(
            path="small.txt",
            lines=(SrcLine(new_line=1, text="ok"),),
        )

        # big contributes 1+4=5 lines and cannot fit.
        # small contributes 1+1=2 lines and can fit.
        bundle, warnings = build_context_bundle(
            [big, small],
            max_total_lines=4,
            max_file_lines=400,
        )

        self.assertNotIn("# SRC: big.txt\n", bundle)
        self.assertIn("# SRC: small.txt\n", bundle)
        self.assertIn("L1: ok\n", bundle)
        self.assertTrue(
            any(
                "context_bundle_total_truncated" in w
                and "limit_lines=4" in w
                and "path=big.txt" in w
                for w in warnings
            )
        )

    def test_sanitizes_path_to_prevent_src_header_injection(self) -> None:
        from killer_7.bundle.context_bundle import build_context_bundle
        from killer_7.bundle.diff_parse import SrcBlock, SrcLine

        block = SrcBlock(
            path="a\nb.txt",
            lines=(SrcLine(new_line=1, text="x"),),
        )

        bundle, warnings = build_context_bundle(
            [block],
            max_total_lines=1500,
            max_file_lines=400,
        )

        self.assertEqual(warnings, [])
        self.assertIn("# SRC: a\\nb.txt\n", bundle)
        self.assertNotIn("# SRC: a\nb.txt\n", bundle)

    def test_file_limit_can_skip_oversized_block_and_include_later_one_for_same_path(
        self,
    ) -> None:
        from killer_7.bundle.context_bundle import build_context_bundle
        from killer_7.bundle.diff_parse import SrcBlock, SrcLine

        big = SrcBlock(
            path="same.txt",
            lines=(
                SrcLine(new_line=1, text="x1"),
                SrcLine(new_line=2, text="x2"),
                SrcLine(new_line=3, text="x3"),
                SrcLine(new_line=4, text="x4"),
            ),
        )
        small = SrcBlock(
            path="same.txt",
            lines=(SrcLine(new_line=10, text="ok"),),
        )

        # big contributes 1+4=5 lines and cannot fit within max_file_lines=4.
        # small contributes 1+1=2 lines and can fit.
        bundle, warnings = build_context_bundle(
            [big, small],
            max_total_lines=1500,
            max_file_lines=4,
        )

        self.assertNotIn("L1: x1\n", bundle)
        self.assertIn("# SRC: same.txt\n", bundle)
        self.assertIn("L10: ok\n", bundle)
        self.assertTrue(
            any(
                "context_bundle_file_truncated" in w
                and "path=same.txt" in w
                and "limit_lines=4" in w
                for w in warnings
            )
        )


if __name__ == "__main__":
    raise SystemExit(unittest.main())

from __future__ import annotations

import unittest


class TestCliInlineArgs(unittest.TestCase):
    def test_review_parser_accepts_inline_flag(self) -> None:
        from killer_7.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["review", "--repo", "owner/name", "--pr", "123", "--inline"]
        )

        self.assertEqual(args.command, "review")
        self.assertTrue(args.inline)
        self.assertFalse(args.post)

    def test_review_parser_accepts_hybrid_multi_args(self) -> None:
        from killer_7.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "review",
                "--repo",
                "owner/name",
                "--pr",
                "123",
                "--hybrid-aspect",
                "correctness",
                "--hybrid-aspect",
                "Security",
                "--hybrid-allowlist",
                "docs/**/*.md",
                "--hybrid-allowlist",
                "killer_7/**/*.py",
            ]
        )

        self.assertEqual(args.hybrid_aspect, ["correctness", "Security"])
        self.assertEqual(
            args.hybrid_allowlist,
            ["docs/**/*.md", "killer_7/**/*.py"],
        )

    def test_review_parser_accepts_aspect_multi_args(self) -> None:
        from killer_7.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "review",
                "--repo",
                "owner/name",
                "--pr",
                "123",
                "--aspect",
                "correctness",
                "--aspect",
                "Security",
            ]
        )

        self.assertEqual(args.aspect, ["correctness", "security"])

    def test_review_parser_accepts_preset_arg(self) -> None:
        from killer_7.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "review",
                "--repo",
                "owner/name",
                "--pr",
                "123",
                "--preset",
                "minimal",
            ]
        )

        self.assertEqual(args.preset, "minimal")

    def test_review_parser_accepts_full_and_no_sot_aspect(self) -> None:
        from killer_7.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "review",
                "--repo",
                "owner/name",
                "--pr",
                "123",
                "--full",
                "--no-sot-aspect",
                "performance",
                "--no-sot-aspect",
                "security",
            ]
        )

        self.assertTrue(args.full)
        self.assertEqual(args.no_sot_aspect, ["performance", "security"])


if __name__ == "__main__":
    raise SystemExit(unittest.main())

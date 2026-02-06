from __future__ import annotations

import unittest


class TestGlob(unittest.TestCase):
    def test_filter_paths_by_globs_supports_double_star_and_sorts(self) -> None:
        from killer_7.glob import filter_paths_by_globs

        paths = [
            "docs/a.md",
            "docs/b.txt",
            "docs/sub/c.md",
            "README.md",
            "./docs/z.md",
            "/docs/rooted.md",
        ]
        patterns = ["docs/**/*.md", "README.md"]

        got = filter_paths_by_globs(paths, patterns)

        self.assertEqual(
            got,
            [
                "README.md",
                "docs/a.md",
                "docs/rooted.md",
                "docs/sub/c.md",
                "docs/z.md",
            ],
        )

    def test_filter_paths_by_globs_supports_directory_double_star_suffix(self) -> None:
        from killer_7.glob import filter_paths_by_globs

        paths = [
            "docs/a.md",
            "docs/sub/c.md",
            "docs/sub/deeper/x.txt",
            "README.md",
        ]

        got = filter_paths_by_globs(paths, ["docs/**"])
        self.assertEqual(
            got,
            [
                "docs/a.md",
                "docs/sub/c.md",
                "docs/sub/deeper/x.txt",
            ],
        )

    def test_filter_paths_by_globs_star_does_not_cross_directory(self) -> None:
        from killer_7.glob import filter_paths_by_globs

        paths = [
            "docs/a.md",
            "docs/sub/c.md",
            "docs/sub/deeper/x.md",
        ]

        self.assertEqual(filter_paths_by_globs(paths, ["docs/*.md"]), ["docs/a.md"])
        self.assertEqual(filter_paths_by_globs(paths, ["docs/*/c.md"]), ["docs/sub/c.md"])

    def test_normalize_repo_relative_path_rejects_dot_segments(self) -> None:
        from killer_7.glob import filter_paths_by_globs, normalize_repo_relative_path

        self.assertEqual(normalize_repo_relative_path("docs/../README.md"), "")
        self.assertEqual(filter_paths_by_globs(["docs/../README.md"], ["docs/**"]), [])


if __name__ == "__main__":
    raise SystemExit(unittest.main())

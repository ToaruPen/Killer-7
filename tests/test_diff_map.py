from __future__ import annotations

import unittest


class TestDiffMap(unittest.TestCase):
    def test_builds_right_line_to_position_map_for_multiple_hunks(self) -> None:
        from killer_7.github.diff_map import build_right_line_to_position_map

        patch = (
            "diff --git a/src/app.py b/src/app.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1,3 +1,4 @@\n"
            " line1\n"
            "-old\n"
            "+new\n"
            " line3\n"
            "+tail\n"
            "@@ -10,2 +11,2 @@\n"
            " context-a\n"
            "-context-b\n"
            "+context-c\n"
        )

        mapping = build_right_line_to_position_map(patch)

        self.assertIn("src/app.py", mapping)
        self.assertEqual(
            mapping["src/app.py"],
            {
                1: 1,
                2: 3,
                3: 4,
                4: 5,
                11: 7,
                12: 9,
            },
        )

    def test_uses_new_path_for_rename_header(self) -> None:
        from killer_7.github.diff_map import build_right_line_to_position_map

        patch = (
            "diff --git a/oldname.txt b/newname.txt\n"
            "similarity index 90%\n"
            "rename from oldname.txt\n"
            "rename to newname.txt\n"
            "--- a/oldname.txt\n"
            "+++ b/newname.txt\n"
            "@@ -1 +1 @@\n"
            "-before\n"
            "+after\n"
        )

        mapping = build_right_line_to_position_map(patch)

        self.assertIn("newname.txt", mapping)
        self.assertNotIn("oldname.txt", mapping)
        self.assertEqual(mapping["newname.txt"], {1: 2})

    def test_returns_empty_mapping_for_none_or_empty_input(self) -> None:
        from killer_7.github.diff_map import build_right_line_to_position_map

        self.assertEqual(build_right_line_to_position_map(None), {})
        self.assertEqual(build_right_line_to_position_map(""), {})

    def test_handles_added_line_starting_with_three_plus_signs(self) -> None:
        from killer_7.github.diff_map import build_right_line_to_position_map

        patch = (
            "diff --git a/src/app.py b/src/app.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1,2 @@\n"
            " keep\n"
            "+++value\n"
        )

        mapping = build_right_line_to_position_map(patch)

        self.assertEqual(mapping["src/app.py"], {1: 1, 2: 2})

    def test_counts_no_newline_marker_in_position_offsets(self) -> None:
        from killer_7.github.diff_map import build_right_line_to_position_map

        patch = (
            "diff --git a/src/app.py b/src/app.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "\\ No newline at end of file\n"
            "@@ -3 +3 @@\n"
            "-before\n"
            "+after\n"
        )

        mapping = build_right_line_to_position_map(patch)

        self.assertEqual(mapping["src/app.py"], {1: 2, 3: 6})


if __name__ == "__main__":
    raise SystemExit(unittest.main())

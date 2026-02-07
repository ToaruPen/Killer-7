from __future__ import annotations

import unittest


class TestDiffParse(unittest.TestCase):
    def test_extracts_head_side_block_for_added_file(self) -> None:
        from killer_7.bundle.diff_parse import parse_diff_patch

        patch = (
            "diff --git a/hello.txt b/hello.txt\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "--- /dev/null\n"
            "+++ b/hello.txt\n"
            "@@ -0,0 +1 @@\n"
            "+hello\n"
        )

        blocks, warnings = parse_diff_patch(patch)

        self.assertEqual(warnings, [])
        self.assertEqual(len(blocks), 1)

        b = blocks[0]
        self.assertEqual(b.path, "hello.txt")
        self.assertGreaterEqual(len(b.lines), 1)
        self.assertEqual(b.lines[0].new_line, 1)
        self.assertEqual(b.lines[0].text, "hello")

    def test_skips_parse_failed_file_and_continues(self) -> None:
        from killer_7.bundle.diff_parse import parse_diff_patch

        patch = (
            "diff --git a/bad.txt b/bad.txt\n"
            "--- a/bad.txt\n"
            "+++ b/bad.txt\n"
            "@@ -x +1 @@\n"
            "+hello\n"
            "diff --git a/good.txt b/good.txt\n"
            "--- /dev/null\n"
            "+++ b/good.txt\n"
            "@@ -0,0 +1 @@\n"
            "+good\n"
        )

        blocks, warnings = parse_diff_patch(patch)

        self.assertEqual([b.path for b in blocks], ["good.txt"])
        self.assertTrue(
            any("kind=parse_failed" in w and "path=bad.txt" in w for w in warnings)
        )

    def test_ignores_deletions_on_head_side(self) -> None:
        from killer_7.bundle.diff_parse import parse_diff_patch

        patch = (
            "diff --git a/foo.txt b/foo.txt\n"
            "index 1111111..2222222 100644\n"
            "--- a/foo.txt\n"
            "+++ b/foo.txt\n"
            "@@ -1,2 +1,2 @@\n"
            "-old\n"
            "+new\n"
            " keep\n"
        )

        blocks, warnings = parse_diff_patch(patch)

        self.assertEqual(warnings, [])
        self.assertEqual([b.path for b in blocks], ["foo.txt"])
        self.assertEqual([x.text for x in blocks[0].lines], ["new", "keep"])
        self.assertEqual([x.new_line for x in blocks[0].lines], [1, 2])

    def test_uses_new_path_for_rename_with_changes(self) -> None:
        from killer_7.bundle.diff_parse import parse_diff_patch

        patch = (
            "diff --git a/oldname.txt b/newname.txt\n"
            "similarity index 80%\n"
            "rename from oldname.txt\n"
            "rename to newname.txt\n"
            "index 1111111..2222222 100644\n"
            "--- a/oldname.txt\n"
            "+++ b/newname.txt\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )

        blocks, warnings = parse_diff_patch(patch)

        self.assertEqual(warnings, [])
        self.assertEqual([b.path for b in blocks], ["newname.txt"])
        self.assertEqual([x.text for x in blocks[0].lines], ["new"])

    def test_skips_deleted_file_and_warns(self) -> None:
        from killer_7.bundle.diff_parse import parse_diff_patch

        patch = (
            "diff --git a/old.txt b/old.txt\n"
            "deleted file mode 100644\n"
            "index 1111111..0000000\n"
            "--- a/old.txt\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-bye\n"
        )

        blocks, warnings = parse_diff_patch(patch)

        self.assertEqual(blocks, [])
        self.assertTrue(
            any("kind=deleted" in w and "path=old.txt" in w for w in warnings)
        )

    def test_skips_binary_file_and_warns(self) -> None:
        from killer_7.bundle.diff_parse import parse_diff_patch

        patch = (
            "diff --git a/img.png b/img.png\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "Binary files /dev/null and b/img.png differ\n"
        )

        blocks, warnings = parse_diff_patch(patch)

        self.assertEqual(blocks, [])
        self.assertTrue(
            any("kind=binary" in w and "path=img.png" in w for w in warnings)
        )

    def test_parses_quoted_paths_in_diff_headers(self) -> None:
        from killer_7.bundle.diff_parse import parse_diff_patch

        patch = (
            'diff --git "a/a b.txt" "b/a b.txt"\n'
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "--- /dev/null\n"
            '+++ "b/a b.txt"\n'
            "@@ -0,0 +1 @@\n"
            "+hello\n"
        )

        blocks, warnings = parse_diff_patch(patch)

        self.assertEqual(warnings, [])
        self.assertEqual([b.path for b in blocks], ["a b.txt"])
        self.assertEqual([x.text for x in blocks[0].lines], ["hello"])

    def test_skips_rename_only_section_without_hunks(self) -> None:
        from killer_7.bundle.diff_parse import parse_diff_patch

        patch = (
            "diff --git a/oldname.txt b/newname.txt\n"
            "similarity index 100%\n"
            "rename from oldname.txt\n"
            "rename to newname.txt\n"
        )

        blocks, warnings = parse_diff_patch(patch)

        self.assertEqual(blocks, [])
        self.assertTrue(
            any("kind=no_hunks" in w and "path=newname.txt" in w for w in warnings)
        )


if __name__ == "__main__":
    raise SystemExit(unittest.main())

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from killer_7.github.gh import GhClient


def _write_fake_gh(path: Path) -> None:
    """Write a fake `gh` binary for GitHub content tests."""

    path.write_text(
        """#!/usr/bin/env python3
import base64
import json
import os
import sys

args = sys.argv[1:]

def bump_counter(label: str) -> None:
    counter = os.environ.get("KILLER7_FAKE_GH_COUNTER")
    if not counter:
        return
    with open(counter, "a", encoding="utf-8") as fh:
        fh.write(label + "\\n")

if args[:1] != ["api"]:
    sys.stderr.write("fake gh: unsupported args: " + " ".join(args) + "\\n")
    raise SystemExit(2)

endpoint = args[-1]

if "/commits/" in endpoint:
    bump_counter("commits")
    sys.stdout.write(json.dumps({"commit": {"tree": {"sha": "TREE123"}}}))
    raise SystemExit(0)

if "/git/trees/" in endpoint:
    bump_counter("trees")
    if os.environ.get("KILLER7_FAKE_GH_TRUNCATED") == "1":
        sys.stdout.write(json.dumps({"truncated": True, "tree": []}))
        raise SystemExit(0)
    sys.stdout.write(
        json.dumps(
            {
                "tree": [
                    {"path": "README.md", "type": "blob", "sha": "B0", "size": 4},
                    {"path": "docs", "type": "tree", "sha": "T0"},
                    {"path": "docs/a.md", "type": "blob", "sha": "B1", "size": 10},
                    {"path": "docs/empty.txt", "type": "blob", "sha": "B4", "size": 0},
                    {"path": "docs/big.txt", "type": "blob", "sha": "B2", "size": 200000},
                    {"path": "docs/sub", "type": "tree", "sha": "T1"},
                    {"path": "docs/sub/c.md", "type": "blob", "sha": "B3", "size": 5},
                ]
            }
        )
    )
    raise SystemExit(0)

if "/contents/" in endpoint:
    bump_counter("contents")
    # Reject fetching big file: code should skip by size before calling contents.
    if endpoint.endswith("/contents/docs/big.txt?ref=deadbeef"):
        sys.stderr.write("fake gh: should not fetch big file contents\\n")
        raise SystemExit(2)

    if endpoint.endswith("/contents/README.md?ref=deadbeef"):
        # GitHub Contents API may include newlines in base64 payload.
        content = base64.b64encode(b"read").decode("ascii")
        content = content[:2] + "\\n" + content[2:]
        sys.stdout.write(
            json.dumps(
                {
                    "type": "file",
                    "encoding": "base64",
                    "size": 4,
                    "path": "README.md",
                    "content": content,
                }
            )
        )
        raise SystemExit(0)

    if endpoint.endswith("/contents/docs/a.md?ref=deadbeef"):
        content = base64.b64encode(b"hello docs").decode("ascii")
        sys.stdout.write(
            json.dumps(
                {
                    "type": "file",
                    "encoding": "base64",
                    "size": 10,
                    "path": "docs/a.md",
                    "content": content,
                }
            )
        )
        raise SystemExit(0)

    if endpoint.endswith("/contents/docs/empty.txt?ref=deadbeef"):
        sys.stdout.write(
            json.dumps(
                {
                    "type": "file",
                    "encoding": "base64",
                    "size": 0,
                    "path": "docs/empty.txt",
                    "content": "",
                }
            )
        )
        raise SystemExit(0)

    if endpoint.endswith("/contents/docs/sub/c.md?ref=deadbeef"):
        content = base64.b64encode(b"c.md").decode("ascii")
        sys.stdout.write(
            json.dumps(
                {
                    "type": "file",
                    "encoding": "base64",
                    "size": 5,
                    "path": "docs/sub/c.md",
                    "content": content,
                }
            )
        )
        raise SystemExit(0)

    if endpoint.endswith("/contents/docs/bad.txt?ref=deadbeef"):
        # Invalid base64 -> should be handled as a warning by fetch_text_files.
        sys.stdout.write(
            json.dumps(
                {
                    "type": "file",
                    "encoding": "base64",
                    "size": 4,
                    "path": "docs/bad.txt",
                    "content": "!!!not_base64!!!",
                }
            )
        )
        raise SystemExit(0)

sys.stderr.write("fake gh: unsupported endpoint: " + endpoint + "\\n")
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


class TestGitHubContent(unittest.TestCase):
    def test_resolve_allowlist_and_fetch_text_files_with_size_limit(self) -> None:
        from killer_7.github.content import GitHubContentFetcher

        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)

            gh = GhClient(bin_path=str(fake_gh))
            fetcher = GitHubContentFetcher(gh=gh, max_bytes=100 * 1024)

            repo = "owner/name"
            ref = "deadbeef"
            allowlist = ["docs/**/*.md", "README.md", "docs/big.txt", "docs/empty.txt"]

            paths = fetcher.resolve_allowlist_paths(
                repo=repo, ref=ref, allowlist=allowlist
            )
            self.assertEqual(
                paths,
                [
                    "README.md",
                    "docs/a.md",
                    "docs/big.txt",
                    "docs/empty.txt",
                    "docs/sub/c.md",
                ],
            )

            result = fetcher.fetch_text_files(repo=repo, ref=ref, paths=paths)
            self.assertEqual(
                result.contents_by_path,
                {
                    "README.md": "read",
                    "docs/a.md": "hello docs",
                    "docs/empty.txt": "",
                    "docs/sub/c.md": "c.md",
                },
            )

            self.assertTrue(
                any(
                    w.kind == "size_limit_exceeded" and w.path == "docs/big.txt"
                    for w in result.warnings
                )
            )

    def test_truncated_tree_is_an_error(self) -> None:
        from killer_7.errors import ExecFailureError
        from killer_7.github.content import GitHubContentFetcher

        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)

            os.environ["KILLER7_FAKE_GH_TRUNCATED"] = "1"
            try:
                gh = GhClient(bin_path=str(fake_gh))
                fetcher = GitHubContentFetcher(gh=gh)

                with self.assertRaises(ExecFailureError):
                    fetcher.resolve_allowlist_paths(
                        repo="owner/name",
                        ref="deadbeef",
                        allowlist=["**/*.md"],
                    )
            finally:
                os.environ.pop("KILLER7_FAKE_GH_TRUNCATED", None)

    def test_contents_is_cached_within_fetcher_instance(self) -> None:
        from killer_7.github.content import GitHubContentFetcher

        with tempfile.TemporaryDirectory() as td:
            counter = Path(td) / "counter.txt"
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)

            os.environ["KILLER7_FAKE_GH_COUNTER"] = str(counter)
            try:
                gh = GhClient(bin_path=str(fake_gh))
                fetcher = GitHubContentFetcher(gh=gh, max_bytes=100 * 1024)

                repo = "owner/name"
                ref = "deadbeef"

                a1 = fetcher.fetch_text_file(repo=repo, ref=ref, path="README.md")
                a2 = fetcher.fetch_text_file(repo=repo, ref=ref, path="README.md")
                self.assertEqual(a1.text, "read")
                self.assertEqual(a2.text, "read")

            finally:
                os.environ.pop("KILLER7_FAKE_GH_COUNTER", None)

            labels = counter.read_text(encoding="utf-8").splitlines()
            self.assertEqual(labels.count("contents"), 1)

    def test_fetch_text_file_failure_is_a_warning(self) -> None:
        """Missing/permission errors should not crash SoT collection."""

        from killer_7.github.content import GitHubContentFetcher

        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)

            gh = GhClient(bin_path=str(fake_gh))
            fetcher = GitHubContentFetcher(gh=gh, max_bytes=100 * 1024)

            res = fetcher.fetch_text_file(
                repo="owner/name", ref="deadbeef", path="docs/missing.md"
            )
            self.assertIsNone(res.text)
            self.assertTrue(any(w.kind == "fetch_failed" for w in res.warnings))

    def test_fetch_text_files_continues_when_one_path_raises(self) -> None:
        from killer_7.github.content import GitHubContentFetcher

        with tempfile.TemporaryDirectory() as td:
            fake_gh = Path(td) / "fake-gh"
            _write_fake_gh(fake_gh)

            gh = GhClient(bin_path=str(fake_gh))
            fetcher = GitHubContentFetcher(gh=gh, max_bytes=100 * 1024)

            result = fetcher.fetch_text_files(
                repo="owner/name",
                ref="deadbeef",
                paths=["README.md", "docs/bad.txt", "docs/a.md"],
            )

            # Other files are still collected.
            self.assertEqual(result.contents_by_path["README.md"], "read")
            self.assertEqual(result.contents_by_path["docs/a.md"], "hello docs")
            self.assertNotIn("docs/bad.txt", result.contents_by_path)

            self.assertTrue(
                any(
                    w.kind == "fetch_failed" and w.path == "docs/bad.txt"
                    for w in result.warnings
                )
            )


if __name__ == "__main__":
    raise SystemExit(unittest.main())

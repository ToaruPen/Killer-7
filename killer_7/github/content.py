"""GitHub content fetch utilities (ref + allowlist oriented).

This module is designed for SoT allowlist collection on a PR branch (ref).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from ..errors import ExecFailureError
from ..glob import filter_paths_by_globs, normalize_repo_relative_path
from .gh import GhClient


DEFAULT_MAX_BYTES = 100 * 1024


@dataclass(frozen=True)
class ContentWarning:
    kind: str
    path: str
    message: str
    size_bytes: int | None = None
    limit_bytes: int | None = None


@dataclass(frozen=True)
class FileContentResult:
    text: str | None
    warnings: tuple[ContentWarning, ...]


@dataclass(frozen=True)
class TextFilesResult:
    contents_by_path: dict[str, str]
    warnings: tuple[ContentWarning, ...]


class GitHubContentFetcher:
    """Fetch repo file contents for a given ref with allowlist support."""

    def __init__(self, *, gh: GhClient | None = None, max_bytes: int = DEFAULT_MAX_BYTES):
        self._gh = gh or GhClient.from_env()
        self._max_bytes = int(max_bytes)
        if self._max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")

        # Caches are per-instance (per-run).
        self._tree_cache: dict[tuple[str, str], list[dict]] = {}
        self._blob_size_cache: dict[tuple[str, str], dict[str, int]] = {}
        self._content_cache: dict[tuple[str, str, str], FileContentResult] = {}

    def resolve_allowlist_paths(
        self, *, repo: str, ref: str, allowlist: list[str]
    ) -> list[str]:
        blob_paths = self._list_blob_paths(repo=repo, ref=ref)
        return filter_paths_by_globs(blob_paths, allowlist)

    def fetch_text_files(
        self, *, repo: str, ref: str, paths: list[str]
    ) -> TextFilesResult:
        contents_by_path: dict[str, str] = {}
        warnings: list[ContentWarning] = []
        for p in paths:
            r = self.fetch_text_file(repo=repo, ref=ref, path=p)
            warnings.extend(r.warnings)
            if r.text is not None:
                contents_by_path[normalize_repo_relative_path(p)] = r.text
        return TextFilesResult(contents_by_path=contents_by_path, warnings=tuple(warnings))

    def fetch_text_file(self, *, repo: str, ref: str, path: str) -> FileContentResult:
        p = normalize_repo_relative_path(path)
        if not p:
            return FileContentResult(
                text=None,
                warnings=(
                    ContentWarning(
                        kind="invalid_path",
                        path="",
                        message="Invalid repo-relative path",
                    ),
                ),
            )
        key = (repo, ref, p)
        cached = self._content_cache.get(key)
        if cached is not None:
            return cached

        size = self._blob_size(repo=repo, ref=ref, path=p)
        if size is not None and size > self._max_bytes:
            res = FileContentResult(
                text=None,
                warnings=(
                    ContentWarning(
                        kind="size_limit_exceeded",
                        path=p,
                        message="Skipped file because it exceeds max_bytes",
                        size_bytes=size,
                        limit_bytes=self._max_bytes,
                    ),
                ),
            )
            self._content_cache[key] = res
            return res

        data = self._gh.repo_contents(repo=repo, path=p, ref=ref)
        warnings: list[ContentWarning] = []

        item_type = (data.get("type") or "").strip()
        if item_type and item_type != "file":
            res = FileContentResult(
                text=None,
                warnings=(
                    ContentWarning(
                        kind="not_a_file",
                        path=p,
                        message=f"Expected file but got type={item_type}",
                    ),
                ),
            )
            self._content_cache[key] = res
            return res

        content_b64 = data.get("content")
        encoding = (data.get("encoding") or "").strip()
        if encoding and encoding != "base64":
            warnings.append(
                ContentWarning(
                    kind="unsupported_encoding",
                    path=p,
                    message=f"Unsupported encoding: {encoding}",
                )
            )
            res = FileContentResult(text=None, warnings=tuple(warnings))
            self._content_cache[key] = res
            return res

        # Note: Empty string is valid for empty files.
        if not isinstance(content_b64, str):
            warnings.append(
                ContentWarning(
                    kind="missing_content",
                    path=p,
                    message="Missing content in contents API output",
                )
            )
            res = FileContentResult(text=None, warnings=tuple(warnings))
            self._content_cache[key] = res
            return res

        # GitHub Contents API may include newlines in base64 payload.
        normalized_b64 = "".join(content_b64.split())
        try:
            raw = base64.b64decode(normalized_b64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ExecFailureError("Invalid base64 content from contents API") from exc

        if len(raw) > self._max_bytes:
            warnings.append(
                ContentWarning(
                    kind="size_limit_exceeded",
                    path=p,
                    message="Skipped file because it exceeds max_bytes",
                    size_bytes=len(raw),
                    limit_bytes=self._max_bytes,
                )
            )
            res = FileContentResult(text=None, warnings=tuple(warnings))
            self._content_cache[key] = res
            return res

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            warnings.append(
                ContentWarning(
                    kind="decode_error",
                    path=p,
                    message="Failed to decode file as UTF-8",
                )
            )
            res = FileContentResult(text=None, warnings=tuple(warnings))
            self._content_cache[key] = res
            return res

        res = FileContentResult(text=text, warnings=tuple(warnings))
        self._content_cache[key] = res
        return res

    def _list_blob_paths(self, *, repo: str, ref: str) -> list[str]:
        items = self._tree_items(repo=repo, ref=ref)
        out: list[str] = []
        for it in items:
            t = (it.get("type") or "").strip()
            if t != "blob":
                continue
            path = normalize_repo_relative_path((it.get("path") or "").strip())
            if path:
                out.append(path)
        return sorted(set(out))

    def _blob_size(self, *, repo: str, ref: str, path: str) -> int | None:
        sizes = self._blob_sizes(repo=repo, ref=ref)
        return sizes.get(path)

    def _blob_sizes(self, *, repo: str, ref: str) -> dict[str, int]:
        key = (repo, ref)
        cached = self._blob_size_cache.get(key)
        if cached is not None:
            return cached

        items = self._tree_items(repo=repo, ref=ref)
        sizes: dict[str, int] = {}
        for it in items:
            if (it.get("type") or "").strip() != "blob":
                continue
            p = normalize_repo_relative_path((it.get("path") or "").strip())
            if not p:
                continue
            size = it.get("size")
            if isinstance(size, int) and size >= 0:
                sizes[p] = size

        self._blob_size_cache[key] = sizes
        return sizes

    def _tree_items(self, *, repo: str, ref: str) -> list[dict]:
        key = (repo, ref)
        cached = self._tree_cache.get(key)
        if cached is not None:
            return cached

        tree_sha = self._gh.repo_commit_tree_sha(repo=repo, ref=ref)
        items = self._gh.repo_tree_recursive(repo=repo, tree_sha=tree_sha)
        self._tree_cache[key] = items
        return items

from __future__ import annotations

import shutil
import subprocess

_GIT_BIN = shutil.which("git")
if _GIT_BIN is None:
    raise RuntimeError("git executable not found")
GIT_BIN: str = _GIT_BIN


def _run_git(td: str, *args: str) -> None:
    subprocess.run(  # noqa: S603
        [GIT_BIN, *args],
        cwd=td,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _git_init(td: str) -> None:
    _run_git(td, "init", "-q")


def _git_add(td: str, pathspec: str) -> None:
    _run_git(td, "add", pathspec)

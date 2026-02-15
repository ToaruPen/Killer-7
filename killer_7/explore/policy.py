from __future__ import annotations

import re
import shlex

from ..errors import BlockedError


_FORBIDDEN_SHELL_CHARS = {
    "\n",
    "$",
    ";",
    "|",
    "&",
    ">",
    "<",
    "`",
}

_FORBIDDEN_GIT_GLOBAL_OPTS = {
    "-c",
    "--config",
    "--git-dir",
    "--work-tree",
    "--exec-path",
    "--paginate",
    "-p",
}

_ALLOWED_GIT_GLOBAL_OPT_KEYS = {
    "--no-pager",
}

_ALLOWED_GIT_SUBCOMMANDS = {
    "diff",
    "log",
    "blame",
    "show",
    "status",
}


def validate_git_readonly_bash_command(command: str) -> None:
    cmd = (command or "").strip()
    if not cmd:
        raise BlockedError("Explore policy violation: empty bash command")
    for ch in _FORBIDDEN_SHELL_CHARS:
        if ch in cmd:
            raise BlockedError("Explore policy violation: shell metacharacters")

    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError as exc:
        raise BlockedError(
            "Explore policy violation: failed to parse bash command"
        ) from exc

    if not tokens or tokens[0] != "git":
        raise BlockedError("Explore policy violation: bash must be a git command")

    i = 1
    global_opts: list[str] = []
    while i < len(tokens) and tokens[i].startswith("-"):
        opt = tokens[i]
        opt_key = opt.split("=", 1)[0]
        if opt_key in _FORBIDDEN_GIT_GLOBAL_OPTS or opt.startswith("-c"):
            raise BlockedError("Explore policy violation: forbidden git global option")
        if opt_key not in _ALLOWED_GIT_GLOBAL_OPT_KEYS:
            raise BlockedError("Explore policy violation: forbidden git global option")
        if opt_key != opt:
            raise BlockedError("Explore policy violation: forbidden git global option")
        global_opts.append(opt_key)
        i += 1

    if "--no-pager" not in global_opts:
        raise BlockedError("Explore policy violation: missing git --no-pager")

    if i >= len(tokens):
        raise BlockedError("Explore policy violation: missing git subcommand")

    sub = tokens[i]
    i += 1
    if sub not in _ALLOWED_GIT_SUBCOMMANDS:
        raise BlockedError("Explore policy violation: forbidden git subcommand")

    args = tokens[i:]

    def is_abs_like_path(value: str) -> bool:
        if not value:
            return False
        norm = value.replace("\\", "/")
        if norm.startswith("/"):
            return True
        if norm.startswith("~"):
            return True
        if re.match(r"^[A-Za-z]:/", norm):
            return True
        return False

    def has_dotdot_segment(value: str) -> bool:
        if not value:
            return False
        norm = value.replace("\\", "/")
        segs = [s for s in norm.split("/") if s]
        return ".." in segs

    def is_forbidden_relpath(value: str) -> bool:
        norm = value.replace("\\", "/")
        segs = [s for s in norm.split("/") if s]
        while segs and segs[0] == ".":
            segs = segs[1:]
        if not segs:
            return False
        if segs[0] in {".git", ".ai-review", ".agentic-sdd"}:
            return True
        if any(s.startswith(".env") for s in segs):
            return True
        return False

    for arg in args:
        if arg == "--output" or arg.startswith("--output="):
            raise BlockedError(
                "Explore policy violation: git args must not use --output"
            )
        if arg.startswith("--ext"):
            raise BlockedError(
                "Explore policy violation: git args must not use --ext-diff"
            )
        if sub == "blame" and (arg.startswith("--c") or arg.startswith("--no-c")):
            raise BlockedError(
                "Explore policy violation: git args must not use --contents"
            )
        if arg == "--contents" or arg.startswith("--contents="):
            raise BlockedError(
                "Explore policy violation: git args must not use --contents"
            )

    if sub == "diff":
        if "--no-index" in args:
            raise BlockedError(
                "Explore policy violation: git diff must not use --no-index"
            )
        if "--no-ext-diff" not in args:
            raise BlockedError(
                "Explore policy violation: git diff missing --no-ext-diff"
            )
        if "--ext-diff" in args:
            raise BlockedError(
                "Explore policy violation: git diff must not use --ext-diff"
            )

        for arg in args:
            if not arg or arg.startswith("-"):
                continue
            if (
                is_abs_like_path(arg)
                or has_dotdot_segment(arg)
                or is_forbidden_relpath(arg)
            ):
                raise BlockedError(
                    "Explore policy violation: git diff must not use outside paths"
                )

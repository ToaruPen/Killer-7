from __future__ import annotations

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

    for arg in args:
        if arg == "--output" or arg.startswith("--output="):
            raise BlockedError(
                "Explore policy violation: git args must not use --output"
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

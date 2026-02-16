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

    def candidate_paths_from_arg(arg: str) -> list[str]:
        if not arg or arg.startswith("-") or arg == "--":
            return []
        if sub == "show" and ":" in arg:
            _, rhs = arg.rsplit(":", 1)
            return [rhs]
        return [arg]

    def show_emits_patch(args_list: list[str]) -> bool:
        emits_patch = True
        for a in args_list:
            if a in {"--no-patch", "-s"}:
                emits_patch = False
                continue
            if a in {"--patch", "-p", "-u"}:
                emits_patch = True
                continue
            if a == "--unified" or a.startswith("--unified="):
                emits_patch = True
                continue
            if a == "-U" or a.startswith("-U"):
                emits_patch = True
        return emits_patch

    def log_emits_patch(args_list: list[str]) -> bool:
        emits_patch = False
        for a in args_list:
            if a in {"--no-patch", "-s"}:
                emits_patch = False
                continue
            if a in {"--patch", "-p", "-u"}:
                emits_patch = True
                continue
            if a == "--unified" or a.startswith("--unified="):
                emits_patch = True
                continue
            if a == "-U" or a.startswith("-U"):
                emits_patch = True
        return emits_patch

    def is_broad_scope_path(value: str) -> bool:
        norm = (value or "").replace("\\", "/").strip()
        if norm in {".", "./"}:
            return True
        segs = [s for s in norm.split("/") if s]
        while segs and segs[0] == ".":
            segs = segs[1:]
        return not segs

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
    else:
        paths: list[str] = []
        if "--" in args:
            j = args.index("--")
            paths.extend([p for p in args[j + 1 :] if p and (not p.startswith("-"))])
        for arg in args:
            paths.extend(candidate_paths_from_arg(arg))

        scope_paths: list[str] = []
        if "--" in args:
            j = args.index("--")
            scope_paths.extend([p for p in args[j + 1 :] if p])
        if sub == "show":
            for arg in args:
                if not arg or arg.startswith("-") or arg == "--":
                    continue
                if ":" in arg:
                    _, rhs = arg.rsplit(":", 1)
                    if rhs:
                        scope_paths.append(rhs)

        for p in scope_paths:
            if p.startswith("-"):
                raise BlockedError(
                    "Explore policy violation: git pathspec must not start with '-'"
                )
            if is_broad_scope_path(p):
                raise BlockedError(
                    "Explore policy violation: git pathspec scope is too broad"
                )
            if is_abs_like_path(p) or has_dotdot_segment(p) or is_forbidden_relpath(p):
                raise BlockedError(
                    "Explore policy violation: git args must not use forbidden paths"
                )

        if sub == "show" and not scope_paths and show_emits_patch(args):
            raise BlockedError(
                "Explore policy violation: git show with patch output must be scoped with '-- <path>'"
            )

        if sub == "log" and not scope_paths and log_emits_patch(args):
            raise BlockedError(
                "Explore policy violation: git log with patch output must be scoped with '-- <path>'"
            )

        for p in paths:
            if is_abs_like_path(p) or has_dotdot_segment(p) or is_forbidden_relpath(p):
                raise BlockedError(
                    "Explore policy violation: git args must not use forbidden paths"
                )

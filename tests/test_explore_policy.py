from __future__ import annotations

import unittest

from killer_7.errors import BlockedError
from killer_7.explore.policy import validate_git_readonly_bash_command


class TestExplorePolicy(unittest.TestCase):
    def test_git_diff_requires_no_pager_and_no_ext_diff(self) -> None:
        validate_git_readonly_bash_command("git --no-pager diff --no-ext-diff")

        with self.assertRaises(BlockedError):
            validate_git_readonly_bash_command("git diff --no-ext-diff")

        with self.assertRaises(BlockedError):
            validate_git_readonly_bash_command("git --no-pager diff")

    def test_git_diff_no_index_blocked(self) -> None:
        with self.assertRaises(BlockedError):
            validate_git_readonly_bash_command(
                "git --no-pager diff --no-ext-diff --no-index /etc/passwd /dev/null"
            )

    def test_git_diff_outside_paths_blocked(self) -> None:
        cases = [
            "git --no-pager diff --no-ext-diff README.md /etc/passwd",
            "git --no-pager diff --no-ext-diff -- README.md /etc/passwd",
            "git --no-pager diff --no-ext-diff ../secret.txt README.md",
            "git --no-pager diff --no-ext-diff -- ../secret.txt README.md",
        ]
        for cmd in cases:
            with self.subTest(cmd=cmd):
                with self.assertRaises(BlockedError):
                    validate_git_readonly_bash_command(cmd)
        validate_git_readonly_bash_command(
            "git --no-pager diff --no-ext-diff main..HEAD"
        )

    def test_git_readonly_subcommands_allowed(self) -> None:
        validate_git_readonly_bash_command("git --no-pager status")
        validate_git_readonly_bash_command("git --no-pager log --oneline -n 5")
        validate_git_readonly_bash_command("git --no-pager show HEAD")
        validate_git_readonly_bash_command("git --no-pager blame README.md")

    def test_git_forbidden_global_opts_blocked_even_when_stuck(self) -> None:
        cases = [
            "git --no-pager --git-dir=/tmp/repo status",
            "git --no-pager --work-tree=/tmp/repo status",
            "git --no-pager --config=foo.bar=baz status",
            "git --no-pager -cfoo=bar status",
        ]
        for cmd in cases:
            with self.subTest(cmd=cmd):
                with self.assertRaises(BlockedError):
                    validate_git_readonly_bash_command(cmd)

    def test_git_global_opts_with_args_cannot_shift_subcommand(self) -> None:
        cases = [
            "git --no-pager -C status push origin HEAD",
            "git --no-pager -O=name status",
        ]
        for cmd in cases:
            with self.subTest(cmd=cmd):
                with self.assertRaises(BlockedError):
                    validate_git_readonly_bash_command(cmd)

    def test_git_args_must_not_write_output_file(self) -> None:
        cases = [
            "git --no-pager show --output=/tmp/x HEAD",
            "git --no-pager log --output=/tmp/x -n 1",
        ]
        for cmd in cases:
            with self.subTest(cmd=cmd):
                with self.assertRaises(BlockedError):
                    validate_git_readonly_bash_command(cmd)

    def test_git_blame_must_not_use_contents(self) -> None:
        cases = [
            "git --no-pager blame --contents=/etc/passwd README.md",
            "git --no-pager blame --contents /etc/passwd README.md",
            "git --no-pager blame --con=/etc/passwd README.md",
            "git --no-pager blame --cont=/etc/passwd README.md",
            "git --no-pager blame --no-cont=/etc/passwd README.md",
        ]
        for cmd in cases:
            with self.subTest(cmd=cmd):
                with self.assertRaises(BlockedError):
                    validate_git_readonly_bash_command(cmd)

    def test_non_git_or_dangerous_commands_blocked(self) -> None:
        with self.assertRaises(BlockedError):
            validate_git_readonly_bash_command("rm -rf .")
        with self.assertRaises(BlockedError):
            validate_git_readonly_bash_command("git push origin HEAD")

    def test_shell_metacharacters_blocked(self) -> None:
        with self.assertRaises(BlockedError):
            validate_git_readonly_bash_command(
                "git --no-pager diff --no-ext-diff && echo oops"
            )
        with self.assertRaises(BlockedError):
            validate_git_readonly_bash_command(
                "git --no-pager diff --no-ext-diff | cat"
            )

    def test_dollar_expansion_blocked(self) -> None:
        with self.assertRaises(BlockedError):
            validate_git_readonly_bash_command(
                "git --no-pager diff --no-ext-diff $(rm -rf .)"
            )
        with self.assertRaises(BlockedError):
            validate_git_readonly_bash_command("git --no-pager log --oneline $HOME")


if __name__ == "__main__":
    raise SystemExit(unittest.main())

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

    def test_git_readonly_subcommands_allowed(self) -> None:
        validate_git_readonly_bash_command("git --no-pager status")
        validate_git_readonly_bash_command("git --no-pager log --oneline -n 5")
        validate_git_readonly_bash_command("git --no-pager show HEAD")
        validate_git_readonly_bash_command("git --no-pager blame README.md")

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

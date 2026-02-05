"""Application errors and exit codes."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Process exit codes (fixed contract).

    - 0: Success
    - 1: Blocked (user action required)
    - 2: Execution failure (invalid input / runtime failure)
    """

    SUCCESS = 0
    BLOCKED = 1
    EXEC_FAILURE = 2


class Killer7Error(Exception):
    """Base application error."""


class BlockedError(Killer7Error):
    """Action is blocked until a prerequisite is satisfied."""


class ExecFailureError(Killer7Error):
    """Execution failed due to invalid input or runtime failure."""

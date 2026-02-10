from __future__ import annotations

import re

from .errors import ExecFailureError


_ASPECT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def normalize_aspect(value: str) -> str:
    a = (value or "").strip().lower()
    a = a.replace("_", "-")
    if not a or not _ASPECT_RE.match(a):
        raise ExecFailureError(f"Invalid aspect: {value!r}")
    return a

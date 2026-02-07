"""Aspect runners.

An "aspect" is a single viewpoint (e.g. correctness) executed against a Context Bundle.
"""

from .orchestrate import ASPECTS_V1, run_all_aspects
from .run_one import run_one_aspect

__all__ = [
    "ASPECTS_V1",
    "run_all_aspects",
    "run_one_aspect",
]

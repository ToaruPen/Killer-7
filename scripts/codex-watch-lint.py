#!/usr/bin/env python3

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _run() -> int:
    from killer_7.lint_watch import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_run())

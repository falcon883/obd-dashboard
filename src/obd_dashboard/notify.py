"""Audible alerts: 3 long beeps = critical, 1 short beep = warning."""

from __future__ import annotations

import sys

try:
    import winsound  # Windows only
except ImportError:  # pragma: no cover
    winsound = None  # type: ignore[assignment]


def beep(level: str) -> None:
    if winsound is None:
        sys.stdout.write("\a")
        sys.stdout.flush()
        return
    crit = level == "CRIT"
    try:
        for _ in range(3 if crit else 1):
            winsound.Beep(  # type: ignore[attr-defined]
                1800 if crit else 1200, 400 if crit else 200
            )
    except RuntimeError:
        pass  # no sound device

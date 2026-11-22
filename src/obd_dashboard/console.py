"""Headless mode: print a live status line and the summary to the terminal."""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from obd_dashboard.types import BaseSink, EventPayload, RowPayload


class ConsoleSink(BaseSink):
    def on_status(self, state: str, message: str, result: Optional[Dict[str, Any]] = None) -> None:
        print(f"\n[{state}] {message}")
        if result:
            print("\n".join(result.get("summary", [])))
            print(f"\nSaved: {result.get('csv')}\n       {result.get('report')}")

    def on_event(self, event: EventPayload) -> None:
        print(f"\n{event['time']} [{event['level']}] {event['msg']}")

    def on_row(self, row: RowPayload) -> None:
        v = row["values"]

        def n(key: str) -> float:
            x = v.get(key)
            return float(x) if isinstance(x, (int, float)) else 0.0

        trim = n("SHORT_FUEL_TRIM_1") + n("LONG_FUEL_TRIM_1")
        sys.stdout.write(
            f"\rRPM {n('RPM'):>5.0f} | {n('SPEED') * 0.621:>3.0f} mph | "
            f"coolant {n('COOLANT_TEMP') * 9 / 5 + 32:>3.0f}F | load {n('ENGINE_LOAD'):>3.0f}% | "
            f"trim {trim:>+5.1f}% | {n('battery_v'):>4.1f}V | MAP {n('INTAKE_PRESSURE'):>3.0f}kPa   "
        )
        sys.stdout.flush()

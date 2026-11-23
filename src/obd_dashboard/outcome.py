"""The numbers behind the "how did the drive go" card shown when a session ends.

Both the real session and the demo feed it one reading per cycle and ask for the same dictionary at the end, so the
screen looks the same either way. The text report has its own, longer summary; this one is for a quick look.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

MAX_GAP_S = 5.0  # a longer pause between readings (link drop, reconnect) is not driven distance
RUNNING_RPM = 500.0  # below this the engine is off; voltage readings then say nothing about the alternator
MIN_REAL_VOLTS = 6.0  # the engine computer reports ~0 V while it shuts down; that is not a battery reading


class DriveTally:
    """Running totals over one drive."""

    def __init__(self) -> None:
        self.distance_km = 0.0
        self.coolant_max: Optional[float] = None
        self._last_t: Optional[float] = None
        self._volts = [0.0, 0]  # sum, count (engine running only)
        self._ltft = [0.0, 0]

    def add(
        self,
        t: float,
        *,
        speed_kph: Optional[float] = None,
        coolant_c: Optional[float] = None,
        rpm: Optional[float] = None,
        volts: Optional[float] = None,
        ltft_pct: Optional[float] = None,
    ) -> None:
        if self._last_t is not None and speed_kph is not None:
            dt = t - self._last_t
            if 0 < dt <= MAX_GAP_S:
                self.distance_km += speed_kph * dt / 3600
        self._last_t = t
        if coolant_c is not None:
            self.coolant_max = coolant_c if self.coolant_max is None else max(self.coolant_max, coolant_c)
        running = rpm is not None and rpm > RUNNING_RPM
        if running and volts is not None and volts >= MIN_REAL_VOLTS:
            self._volts[0] += volts
            self._volts[1] += 1
        if running and ltft_pct is not None:
            self._ltft[0] += ltft_pct
            self._ltft[1] += 1

    @staticmethod
    def _mean(pair: List[float]) -> Optional[float]:
        return round(pair[0] / pair[1], 2) if pair[1] else None

    def outcome(
        self,
        *,
        verdict: str,
        duration_s: float,
        rows: int,
        start_coolant_c: Optional[float],
        warm_s: Dict[Any, float],
        alerts: Iterable[str],
        stored: Iterable[str],
        pending: Iterable[str],
        mil: Optional[bool],
        monitor_failures: Iterable[str] = (),
        end_answered: bool = True,
        demo: bool = False,
    ) -> Dict[str, Any]:
        return {
            "verdict": verdict,
            "duration_s": round(duration_s, 1),
            "rows": rows,
            "rows_per_s": round(rows / duration_s, 1) if duration_s > 0 else None,
            "distance_km": round(self.distance_km, 1),
            "start_coolant_c": start_coolant_c,
            "coolant_max_c": self.coolant_max,
            "warm_s": {str(k): round(v, 1) for k, v in warm_s.items()},
            "battery_avg_v": self._mean(self._volts),
            "ltft_avg_pct": self._mean(self._ltft),
            "alerts": list(alerts),
            "stored": list(stored),
            "pending": list(pending),
            "mil": mil,
            "monitor_failures": list(monitor_failures),
            "end_answered": end_answered,
            "demo": demo,
        }

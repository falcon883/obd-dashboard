"""Per-drive numbers for the History screen, worked out from each drive's CSV log.

Every number is computed from the CSV, so drives logged by older versions of the app show up too, and a
drive that crashed before it wrote its summary still counts. Results are cached until the file changes.
"""

from __future__ import annotations

import csv
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from obd_dashboard.garage import Garage

RUNNING_RPM = 500  # same idea as the live "engine is running" test
MIN_TREND_SECONDS = 60  # shorter logs (a quick adapter test) are listed but left out of the trends
MIN_SAMPLES = 10  # an average over fewer rows than this is noise, so it is left blank
COLD_START_C = 60  # warm-up time only means something if the engine started cold
MIN_REAL_VOLTS = 6.0  # below this the engine computer was shutting down, not a flat battery
WARM_C = 80  # "warm" for the idle-speed number
MAX_GAP_S = 5.0  # a gap in the log longer than this does not count towards distance

Key = Tuple[str, int, int]


def _num(row: Dict[str, str], column: str) -> Optional[float]:
    try:
        text = row.get(column)
        return float(text) if text not in (None, "") else None
    except ValueError:
        return None


def _mean(values: Iterable[float]) -> Optional[float]:
    items = list(values)
    return round(sum(items) / len(items), 2) if len(items) >= MIN_SAMPLES else None


def drive_stats(csv_path: Path) -> Dict[str, Any]:
    """Headline numbers for one drive. A value the log cannot support is None, never a guess."""
    start_cool: Optional[float] = None
    cool_max: Optional[float] = None
    warm: Dict[int, float] = {}
    volts: List[float] = []
    ltft: List[float] = []
    idle: List[float] = []
    km = 0.0
    rows = 0
    last_t: Optional[float] = None
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            t = _num(row, "elapsed_s")
            if t is None:
                continue
            rows += 1
            rpm, speed, cool = _num(row, "rpm"), _num(row, "speed_kph"), _num(row, "coolant_temp_c")
            running = rpm is not None and rpm > RUNNING_RPM
            if cool is not None:
                if start_cool is None:
                    start_cool = cool
                cool_max = cool if cool_max is None else max(cool_max, cool)
                for mark in (70, 80):
                    if cool >= mark and mark not in warm:
                        warm[mark] = t / 60
            if running:
                v, trim = _num(row, "battery_v"), _num(row, "long_fuel_trim_1_pct")
                if v is not None and v >= MIN_REAL_VOLTS:
                    volts.append(v)
                if trim is not None:
                    ltft.append(trim)
                if speed == 0 and cool is not None and cool >= WARM_C and rpm is not None and rpm < 1500:
                    idle.append(rpm)
            if speed is not None and last_t is not None and 0 < t - last_t <= MAX_GAP_S:
                km += speed * (t - last_t) / 3600
            last_t = t
    cold = start_cool is not None and start_cool < COLD_START_C
    return {
        "rows": rows,
        "duration_s": round(last_t, 1) if last_t is not None else None,
        "start_coolant_c": start_cool,
        "coolant_max_c": cool_max,
        "warm_70_min": round(warm[70], 1) if cold and 70 in warm else None,
        "warm_80_min": round(warm[80], 1) if cold and 80 in warm else None,
        "battery_avg_v": _mean(volts),
        "ltft_avg_pct": _mean(ltft),
        "warm_idle_rpm": _mean(idle),
        "distance_km": round(km, 1),
    }


class History:
    """Reads a car's drives from the garage, oldest first, with the numbers above."""

    def __init__(self, garage: Garage) -> None:
        self._garage = garage
        self._cache: Dict[Key, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _stats(self, path: Path) -> Dict[str, Any]:
        info = path.stat()
        key = (str(path), info.st_mtime_ns, info.st_size)
        with self._lock:
            found = self._cache.get(key)
        if found is None:
            found = drive_stats(path)
            with self._lock:
                self._cache[key] = found
        return found

    def drives(self, vin: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for session in reversed(self._garage.sessions(vin)):  # sessions() is newest first
            path = self._garage.car_dir(vin) / session["files"]["csv"]
            try:
                stats = self._stats(path)
            except (OSError, UnicodeDecodeError, csv.Error):
                continue  # an unreadable log should not take the whole screen down
            duration = stats["duration_s"] if stats["duration_s"] is not None else session.get("duration_s")
            out.append(
                {
                    "stamp": session["stamp"],
                    "complete": session["complete"],
                    "verdict": session.get("verdict"),
                    "alerts": session.get("alerts"),
                    "files": session["files"],
                    **{k: v for k, v in stats.items() if k != "duration_s"},
                    "duration_s": duration,
                    "in_trends": duration is not None and duration >= MIN_TREND_SECONDS,
                }
            )
        return out

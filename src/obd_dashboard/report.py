"""Session output: CSV columns, the text report file, and the end-of-run summary."""

from __future__ import annotations

import csv
import datetime
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, List, Mapping, Optional, Sequence

UNIT_ABBR = {
    "degree_Celsius": "c", "kilopascal": "kpa", "kilometer_per_hour": "kph", "percent": "pct",
    "volt": "v", "revolutions_per_minute": "rpm", "degree": "deg", "second": "s", "minute": "min",
    "kilometer": "km", "pascal": "pa", "count": "cnt", "milliampere": "ma", "ampere": "a",
    "ratio": "ratio", "gram_per_second": "gps", "ohm": "ohm", "liter_per_hour": "lph",
    "hour": "h", "millivolt": "mv",
}  # fmt: skip

EXTRA_COLUMNS = ["battery_v", "coolant_f", "speed_mph", "trim_total_pct", "mil", "dtc_stored", "dtc_pending"]
VERDICTS = {0: "OK - no alerts", 1: "WARNINGS - see alerts", 2: "CRITICAL - see alerts"}


class Stat:
    """Running min / mean / max."""

    __slots__ = ("n", "lo", "hi", "total")

    def __init__(self) -> None:
        self.n = 0
        self.lo = float("inf")
        self.hi = float("-inf")
        self.total = 0.0

    def add(self, v: float) -> None:
        self.n += 1
        self.lo, self.hi, self.total = min(self.lo, v), max(self.hi, v), self.total + v

    @property
    def mean(self) -> float:
        return self.total / self.n if self.n else float("nan")


def column_name(sensor: str, units: Mapping[str, str]) -> str:
    """CSV header for a sensor: 'coolant_temp_c', but never 'rpm_rpm'."""
    base = sensor.lower()
    if sensor == "FUEL_STATUS" or sensor not in units:
        return "fuel_status" if sensor == "FUEL_STATUS" else base
    abbr = UNIT_ABBR.get(units[sensor], units[sensor])
    return base if base.endswith(abbr) else f"{base}_{abbr}"


def csv_fields(sensors: Sequence[str], units: Mapping[str, str], misfire_keys: Sequence[str]) -> List[str]:
    return (
        ["time", "elapsed_s"]
        + [column_name(s, units) for s in sensors]
        + EXTRA_COLUMNS
        + [f"misfire_{k}_cur" for k in sorted(misfire_keys)]
    )


class SessionFiles(AbstractContextManager):  # type: ignore[type-arg]
    """The CSV + text report for one session. Always closed, even if the session crashes."""

    def __init__(self, directory: Path, stamp: Optional[str] = None) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.stamp = stamp or f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
        self.csv_path = directory / f"{self.stamp}_data.csv"
        self.report_path = directory / f"{self.stamp}_report.txt"
        self.summary_path = directory / f"{self.stamp}_summary.json"
        self._report: IO[str] = self.report_path.open("w", encoding="utf-8")  # noqa: SIM115 - closed in close()
        self._csv_file: Optional[IO[str]] = None
        self._writer: Optional[csv.DictWriter[str]] = None

    def log(self, line: str = "") -> None:
        self._report.write(line + "\n")
        self._report.flush()

    def log_lines(self, lines: Sequence[str]) -> None:
        for line in lines:
            self.log(line)

    def write_summary(self, data: Mapping[str, Any]) -> None:
        self.summary_path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")

    def start_csv(self, fields: Sequence[str]) -> None:
        self._csv_file = self.csv_path.open("w", newline="", encoding="utf-8")  # noqa: SIM115 - closed in close()
        self._writer = csv.DictWriter(self._csv_file, fieldnames=list(fields), extrasaction="ignore")
        self._writer.writeheader()

    def write_row(self, row: Mapping[str, Any]) -> None:
        if self._writer is None or self._csv_file is None:
            raise RuntimeError("start_csv() must be called first")
        self._writer.writerow(row)
        self._csv_file.flush()

    def close(self) -> None:
        for f in (self._csv_file, self._report):
            if f is not None and not f.closed:
                f.close()

    def __exit__(self, *exc: object) -> None:
        self.close()


@dataclass
class SummaryData:
    worst: int  # 0 ok, 1 warn, 2 crit
    duration_s: float
    loops: int
    start_cool: Optional[float]
    warm: Mapping[int, float]  # threshold C -> seconds into the session
    end_codes: Mapping[str, Any]
    misfire_start: Optional[float]
    misfire_end: Optional[float]
    monitor_failures: Sequence[str]
    alerts_raised: Sequence[str]
    sensors: Sequence[str]  # display order
    units: Mapping[str, str]
    stats: Mapping[str, Stat]
    static_start: Mapping[str, Any] = field(default_factory=dict)
    static_end: Mapping[str, Any] = field(default_factory=dict)
    end_answered: bool = True  # False when the car had stopped answering by the end (ignition off, link lost)


def render_summary(d: SummaryData) -> List[str]:
    start = f"{d.start_cool:.0f}C" if d.start_cool is not None else "?"
    reached = ", ".join(f"{t}C at {d.warm[t] / 60:.1f} min" for t in sorted(d.warm)) or (
        "no checkpoint (stayed under 70C)"
    )
    out = [
        "",
        "=== SUMMARY ===",
        f"Overall: {VERDICTS[d.worst]}",
        f"Duration {d.duration_s / 60:.1f} min | {d.loops} rows | avg {d.duration_s / max(d.loops, 1):.2f} s/row",
        f"Coolant warm-up: start {start}, reached {reached}",
        f"Codes at end: stored {d.end_codes.get('stored') or 'none'} | "
        f"pending {d.end_codes.get('pending') or 'none'} | MIL {d.end_codes.get('mil')}"
        + ("" if d.end_answered else "  (last known: the car had stopped answering)"),
        f"Misfire counters: start {d.misfire_start} -> end {d.misfire_end}",
        ("Mode 06 failures at end: " if d.end_answered else "Mode 06 failures (last known, car stopped answering): ")
        + ("; ".join(d.monitor_failures) if d.monitor_failures else "none"),
        "Alerts raised: " + (" | ".join(d.alerts_raised) if d.alerts_raised else "none"),
        "",
        f"{'sensor':<28}{'unit':<22}{'min':>10}{'avg':>10}{'max':>10}",
    ]
    for name in d.sensors:
        s = d.stats.get(name)
        if s and s.n:
            out.append(f"{name:<28}{d.units.get(name, ''):<22}{s.lo:>10.2f}{s.mean:>10.2f}{s.hi:>10.2f}")
    if d.static_end:
        out += [
            "",
            "Counters start -> end: "
            + ", ".join(f"{k} {d.static_start.get(k)} -> {v}" for k, v in d.static_end.items()),
        ]
    return out

"""Health rules. Pure functions: readings + session state in, alerts out (easy to unit-test)."""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from obd_dashboard.types import Alert

# ---- thresholds (all in the car's native units: Celsius, volts, percent, rpm) ----
RUNNING_RPM = 400
COOLANT_WARN_C = 102
COOLANT_CRIT_C = 108
WARMED_UP_C = 80
WARMUP_CHECK_AFTER_S = 1200
BATTERY_LOW_RUNNING_V = 13.0
BATTERY_HIGH_RUNNING_V = 15.0
BATTERY_LOW_OFF_V = 12.0
LTFT_WARN_PCT = 10
LTFT_CRIT_PCT = 20
STFT_WINDOW = 30
STFT_WARN_PCT = 15
IDLE_RPM_RANGE = (500, 1100)
CATALYST_WARN_C = 950
CATALYST_CRIT_C = 1000
FUEL_LOW_PCT = 10
MISFIRE_RISE = 10

Readings = Dict[str, object]
Alerts = Dict[str, Alert]


@dataclass
class RuleState:
    """Facts the rules need beyond the current reading."""

    stft: Deque[float] = field(default_factory=lambda: deque(maxlen=STFT_WINDOW))
    drove: bool = False
    run_start: Optional[float] = None  # monotonic seconds when the engine first ran
    misfire0: Optional[float] = None  # misfire total at the start of the session
    misfire: Dict[str, float] = field(default_factory=dict)
    mil: Optional[bool] = None
    stored: List[str] = field(default_factory=list)
    pending: List[str] = field(default_factory=list)


def _num(readings: Readings, key: str) -> Optional[float]:
    v = readings.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def _coolant(r: Readings, s: RuleState, now: float) -> Alerts:
    cool = _num(r, "COOLANT_TEMP")
    if cool is None:
        return {}
    out: Alerts = {}
    label = f"{cool:.0f}C ({_c_to_f(cool):.0f}F)"
    if cool >= COOLANT_CRIT_C:
        out["coolant"] = Alert("CRIT", f"Coolant {label} - overheating, pull over and shut off")
    elif cool >= COOLANT_WARN_C:
        out["coolant"] = Alert("WARN", f"Coolant running hot: {label}")
    if s.drove and s.run_start is not None and now - s.run_start > WARMUP_CHECK_AFTER_S and cool < WARMED_UP_C:
        out["warmup"] = Alert("WARN", f"Coolant only {cool:.0f}C after 20+ min incl. driving (thermostat stuck open?)")
    return out


def _battery(r: Readings, running: bool) -> Alerts:
    v = _num(r, "battery_v")
    if v is None:
        return {}
    if running and v < BATTERY_LOW_RUNNING_V:
        return {"battery": Alert("WARN", f"Charging low: {v:.1f}V while running (alternator/belt/battery)")}
    if running and v > BATTERY_HIGH_RUNNING_V:
        return {"battery": Alert("WARN", f"Overcharging: {v:.1f}V")}
    if not running and v < BATTERY_LOW_OFF_V:
        return {"battery": Alert("WARN", f"Weak battery: {v:.1f}V with engine off")}
    return {}


def _fuel_trim(r: Readings, s: RuleState) -> Alerts:
    out: Alerts = {}
    lt = _num(r, "LONG_FUEL_TRIM_1")
    if lt is not None and abs(lt) >= LTFT_WARN_PCT:
        kind = "lean (vacuum leak / MAF / low fuel pressure)" if lt > 0 else "rich (injectors / O2 / fuel leak)"
        level = "CRIT" if abs(lt) >= LTFT_CRIT_PCT else "WARN"
        out["ltft"] = Alert(level, f"Long-term fuel trim {lt:+.1f}% -> {kind}")
    if len(s.stft) >= STFT_WINDOW:
        avg = statistics.mean(s.stft)
        if abs(avg) >= STFT_WARN_PCT:
            out["stft"] = Alert("WARN", f"Short-term fuel trim averaging {avg:+.1f}%")
    return out


def _idle(r: Readings, running: bool) -> Alerts:
    rpm, cool, spd = _num(r, "RPM"), _num(r, "COOLANT_TEMP"), _num(r, "SPEED")
    lo, hi = IDLE_RPM_RANGE
    warm_idle = running and rpm is not None and cool is not None and cool > WARMED_UP_C and spd == 0
    if warm_idle and rpm is not None and not lo <= rpm <= hi:
        return {"idle": Alert("WARN", f"Unusual warm idle: {rpm:.0f} rpm")}
    return {}


def _catalyst(r: Readings) -> Alerts:
    temps = [v for k, v in r.items() if k.startswith("CATALYST_TEMP") and isinstance(v, float)]
    if temps and max(temps) >= CATALYST_WARN_C:
        hot = max(temps)
        level = "CRIT" if hot >= CATALYST_CRIT_C else "WARN"
        return {"cat": Alert(level, f"Catalyst temperature {hot:.0f}C - too hot")}
    return {}


def _fuel_level(r: Readings) -> Alerts:
    fl = _num(r, "FUEL_LEVEL")
    if fl is not None and fl < FUEL_LOW_PCT:
        return {"fuel": Alert("WARN", f"Fuel level low: {fl:.0f}%")}
    return {}


def _misfire(s: RuleState) -> Alerts:
    now_total, start = s.misfire.get("total"), s.misfire0
    if now_total is not None and start is not None and now_total - start >= MISFIRE_RISE:
        return {"misfire": Alert("WARN", f"Misfire counter rising: {start:.0f} -> {now_total:.0f} this drive cycle")}
    return {}


def _codes(s: RuleState) -> Alerts:
    out: Alerts = {}
    if s.mil:
        out["mil"] = Alert("CRIT", "Check-engine light is ON")
    if s.stored:
        out["dtc"] = Alert("CRIT", "Stored trouble codes: " + "; ".join(s.stored))
    if s.pending:
        out["pending"] = Alert("WARN", "Pending trouble codes: " + "; ".join(s.pending))
    return out


def evaluate(readings: Readings, state: RuleState, now: float) -> Alerts:
    """Everything currently out of range, keyed by topic. `now` is monotonic seconds."""
    rpm = _num(readings, "RPM")
    running = rpm is not None and rpm > RUNNING_RPM
    checks: Tuple[Alerts, ...] = (
        _coolant(readings, state, now),
        _battery(readings, running),
        _fuel_trim(readings, state),
        _idle(readings, running),
        _catalyst(readings),
        _fuel_level(readings),
        _misfire(state),
        _codes(state),
    )
    merged: Alerts = {}
    for found in checks:
        merged.update(found)
    return merged

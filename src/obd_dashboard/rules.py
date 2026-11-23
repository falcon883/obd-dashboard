"""Health rules. Pure functions: readings + session state + limits in, alerts out (easy to unit-test).

The limits live in `userconfig.Thresholds` (defaults there, editable on the Settings screen)."""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from obd_dashboard.types import Alert
from obd_dashboard.userconfig import DEFAULT_THRESHOLDS, Thresholds

Readings = Dict[str, object]
Alerts = Dict[str, Alert]

# Cranking and the first second after start dip the voltage for a moment. Only a reading that stays bad is a problem.
BATTERY_SUSTAIN_S = 5.0
STFT_FULL_SHARE = 0.8  # the short-term trim average needs this share of its window before it can alert


@dataclass
class RuleState:
    """Facts the rules need beyond the current reading."""

    stft: Deque[Tuple[float, float]] = field(default_factory=deque)  # (monotonic seconds, short-term trim %)
    drove: bool = False
    run_start: Optional[float] = None  # monotonic seconds when the engine first ran
    misfire0: Optional[float] = None  # misfire total at the start of the session
    misfire: Dict[str, float] = field(default_factory=dict)
    mil: Optional[bool] = None
    stored: List[str] = field(default_factory=list)
    pending: List[str] = field(default_factory=list)
    battery_kind: Optional[str] = None  # which battery problem is showing right now, if any
    battery_since: float = 0.0  # monotonic seconds when that problem first showed

    @classmethod
    def for_limits(cls, t: Thresholds) -> RuleState:
        return cls()

    def add_stft(self, now: float, value: float, window_s: float) -> None:
        """Keep the last `window_s` seconds of short-term trim, however fast the readings come in."""
        self.stft.append((now, value))
        while self.stft and now - self.stft[0][0] > window_s:
            self.stft.popleft()


def _num(readings: Readings, key: str) -> Optional[float]:
    v = readings.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def _coolant(r: Readings, s: RuleState, now: float, t: Thresholds) -> Alerts:
    cool = _num(r, "COOLANT_TEMP")
    if cool is None:
        return {}
    out: Alerts = {}
    label = f"{cool:.0f}C ({_c_to_f(cool):.0f}F)"
    if cool >= t.coolant_crit_c:
        out["coolant"] = Alert("CRIT", f"Coolant {label} - overheating, pull over and shut off")
    elif cool >= t.coolant_warn_c:
        out["coolant"] = Alert("WARN", f"Coolant running hot: {label}")
    after_s = t.warmup_check_after_min * 60
    if s.drove and s.run_start is not None and now - s.run_start > after_s and cool < t.warmed_up_c:
        mins = f"{t.warmup_check_after_min:g}"
        out["warmup"] = Alert(
            "WARN", f"Coolant only {cool:.0f}C after {mins}+ min incl. driving (thermostat stuck open?)"
        )
    return out


def _battery(r: Readings, running: bool, s: RuleState, now: float, t: Thresholds) -> Alerts:
    v = _num(r, "battery_v")
    kind: Optional[str] = None
    msg = ""
    if v is not None:
        if running and v < t.battery_low_running_v:
            kind, msg = "low_running", f"Charging low: {v:.1f}V while running (alternator/belt/battery)"
        elif running and v > t.battery_high_running_v:
            kind, msg = "high_running", f"Overcharging: {v:.1f}V"
        elif not running and v < t.battery_low_off_v:
            kind, msg = "low_off", f"Weak battery: {v:.1f}V with engine off"
    if kind is None:
        s.battery_kind = None
        return {}
    if kind != s.battery_kind:
        s.battery_kind, s.battery_since = kind, now
    if now - s.battery_since < BATTERY_SUSTAIN_S:
        return {}
    return {"battery": Alert("WARN", msg)}


def _fuel_trim(r: Readings, s: RuleState, t: Thresholds) -> Alerts:
    out: Alerts = {}
    lt = _num(r, "LONG_FUEL_TRIM_1")
    if lt is not None and abs(lt) >= t.ltft_warn_pct:
        kind = "lean (vacuum leak / MAF / low fuel pressure)" if lt > 0 else "rich (injectors / O2 / fuel leak)"
        level = "CRIT" if abs(lt) >= t.ltft_crit_pct else "WARN"
        out["ltft"] = Alert(level, f"Long-term fuel trim {lt:+.1f}% -> {kind}")
    if s.stft and s.stft[-1][0] - s.stft[0][0] >= STFT_FULL_SHARE * t.stft_window:  # enough history to trust
        avg = statistics.mean(v for _, v in s.stft)
        if abs(avg) >= t.stft_warn_pct:
            out["stft"] = Alert("WARN", f"Short-term fuel trim averaging {avg:+.1f}%")
    return out


def _idle(r: Readings, running: bool, t: Thresholds) -> Alerts:
    rpm, cool, spd = _num(r, "RPM"), _num(r, "COOLANT_TEMP"), _num(r, "SPEED")
    lo, hi = t.idle_rpm_min, t.idle_rpm_max
    warm_idle = running and rpm is not None and cool is not None and cool > t.warmed_up_c and spd == 0
    if warm_idle and rpm is not None and not lo <= rpm <= hi:
        return {"idle": Alert("WARN", f"Unusual warm idle: {rpm:.0f} rpm")}
    return {}


def _catalyst(r: Readings, t: Thresholds) -> Alerts:
    temps = [v for k, v in r.items() if k.startswith("CATALYST_TEMP") and isinstance(v, float)]
    if temps and max(temps) >= t.catalyst_warn_c:
        hot = max(temps)
        level = "CRIT" if hot >= t.catalyst_crit_c else "WARN"
        return {"cat": Alert(level, f"Catalyst temperature {hot:.0f}C - too hot")}
    return {}


def _fuel_level(r: Readings, t: Thresholds) -> Alerts:
    fl = _num(r, "FUEL_LEVEL")
    if fl is not None and fl < t.fuel_low_pct:
        return {"fuel": Alert("WARN", f"Fuel level low: {fl:.0f}%")}
    return {}


def _misfire(s: RuleState, t: Thresholds) -> Alerts:
    now_total, start = s.misfire.get("total"), s.misfire0
    if now_total is not None and start is not None and now_total - start >= t.misfire_rise:
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


def evaluate(readings: Readings, state: RuleState, now: float, limits: Thresholds = DEFAULT_THRESHOLDS) -> Alerts:
    """Everything currently out of range, keyed by topic. `now` is monotonic seconds."""
    rpm = _num(readings, "RPM")
    running = rpm is not None and rpm > limits.running_rpm
    checks: Tuple[Alerts, ...] = (
        _coolant(readings, state, now, limits),
        _battery(readings, running, state, now, limits),
        _fuel_trim(readings, state, limits),
        _idle(readings, running, limits),
        _catalyst(readings, limits),
        _fuel_level(readings, limits),
        _misfire(state, limits),
        _codes(state),
    )
    merged: Alerts = {}
    for found in checks:
        merged.update(found)
    return merged

"""User-editable settings: alert limits (global, or per car) and advanced logger options.

Stored as one small JSON file (`settings.json`) next to the car folders. Only values that differ from the
built-in defaults are saved ("overrides"), so a future change to a default reaches everyone who never touched it.
The same field table drives validation here and the Settings screen in the browser, so they cannot drift apart.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from obd_dashboard.garage import atomic_write

SETTINGS_FILE = "settings.json"


class ConfigError(ValueError):
    """The submitted values are not acceptable. `problems` lists every reason, ready to show to the user."""

    def __init__(self, problems: List[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    default: Any
    kind: str = "number"  # number | int | bool | temp  (temp = degrees Celsius, shown in the user's unit)
    unit: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    step: float = 1
    help: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}

    def parse(self, raw: Any) -> Any:
        """Strict: return a clean value or raise ValueError with a message about this field."""
        if self.kind == "bool":
            if not isinstance(raw, bool):
                raise ValueError(f"{self.label}: must be on or off")
            return raw
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw != raw:  # bool, text, NaN
            raise ValueError(f"{self.label}: must be a number")
        value = float(raw)
        if self.kind == "int":
            if value != int(value):
                raise ValueError(f"{self.label}: must be a whole number")
            value = int(value)
        else:
            value = round(value, 2)
        if (self.min is not None and value < self.min) or (self.max is not None and value > self.max):
            unit = "°C" if self.kind == "temp" else self.unit
            raise ValueError(f"{self.label}: must be between {self.min:g} and {self.max:g} {unit}".rstrip())
        return value


@dataclass(frozen=True)
class Thresholds:
    """Alert limits in the car's own units (Celsius, volts, percent, rpm)."""

    running_rpm: int = 400
    coolant_cold_c: float = 70
    warmed_up_c: float = 80
    coolant_warn_c: float = 102
    coolant_crit_c: float = 108
    warmup_check_after_min: float = 20
    battery_low_running_v: float = 13.0
    battery_high_running_v: float = 15.0
    battery_low_off_v: float = 12.0
    ltft_warn_pct: float = 10
    ltft_crit_pct: float = 20
    stft_warn_pct: float = 15
    stft_window: int = 30
    idle_rpm_min: int = 500
    idle_rpm_max: int = 1100
    catalyst_warn_c: float = 950
    catalyst_crit_c: float = 1000
    fuel_low_pct: float = 10
    misfire_rise: int = 10


DEFAULT_THRESHOLDS = Thresholds()

_G_ENGINE, _G_COOLANT, _G_BATTERY = "Engine", "Coolant", "Battery & charging"
_G_FUEL, _G_EXHAUST, _G_OTHER = "Fuel trim", "Exhaust & misfires", "Other"

# fmt: off
THRESHOLD_FIELDS: Tuple[Field, ...] = (
    Field("running_rpm", "Engine counts as running above", _G_ENGINE, 400, "int", "rpm", 200, 1500, 50,
          "Below this the car is treated as engine-off (changes the battery checks)."),
    Field("idle_rpm_min", "Warm idle: lowest normal", _G_ENGINE, 500, "int", "rpm", 300, 1500, 50,
          "Warn when a warm, stopped engine idles below this."),
    Field("idle_rpm_max", "Warm idle: highest normal", _G_ENGINE, 1100, "int", "rpm", 600, 3000, 50,
          "...or above this."),
    Field("coolant_cold_c", "'Warming up' until", _G_COOLANT, 70, "temp", "", 30, 95, 1,
          "Display only: the dashboard says 'Warming up' below this."),
    Field("warmed_up_c", "Counts as warmed up at", _G_COOLANT, 80, "temp", "", 60, 100, 1,
          "Used for the thermostat check and the warm-idle check."),
    Field("coolant_warn_c", "Coolant warning", _G_COOLANT, 102, "temp", "", 90, 125, 1),
    Field("coolant_crit_c", "Coolant critical", _G_COOLANT, 108, "temp", "", 95, 135, 1,
          "Alert says to pull over and shut off."),
    Field("warmup_check_after_min", "Thermostat check after", _G_COOLANT, 20, "number", "min", 5, 90, 1,
          "Warn if the coolant is still below 'warmed up' this long after the engine started and you drove."),
    Field("battery_low_running_v", "Charging low below", _G_BATTERY, 13.0, "number", "V", 11.5, 14.4, 0.1,
          "Engine running."),
    Field("battery_high_running_v", "Overcharging above", _G_BATTERY, 15.0, "number", "V", 14.4, 16.5, 0.1,
          "Engine running."),
    Field("battery_low_off_v", "Weak battery below", _G_BATTERY, 12.0, "number", "V", 11.0, 12.8, 0.1,
          "Engine off."),
    Field("ltft_warn_pct", "Long-term trim warning (±)", _G_FUEL, 10, "number", "%", 3, 40, 1),
    Field("ltft_crit_pct", "Long-term trim critical (±)", _G_FUEL, 20, "number", "%", 5, 50, 1),
    Field("stft_warn_pct", "Short-term trim average warning (±)", _G_FUEL, 15, "number", "%", 3, 40, 1),
    Field("stft_window", "Short-term trim average over", _G_FUEL, 30, "int", "readings", 5, 300, 5,
          "About one reading per second."),
    Field("catalyst_warn_c", "Catalyst warning", _G_EXHAUST, 950, "temp", "", 600, 1200, 10,
          "A normal full-throttle drive can reach about 930 °C, so the default leaves room."),
    Field("catalyst_crit_c", "Catalyst critical", _G_EXHAUST, 1000, "temp", "", 650, 1300, 10),
    Field("misfire_rise", "Misfire counter rise", _G_EXHAUST, 10, "int", "counts", 1, 500, 1,
          "Warn when the misfire total grows this much during one session."),
    Field("fuel_low_pct", "Low fuel below", _G_OTHER, 10, "number", "%", 3, 50, 1),
)
# fmt: on

ADVANCED_DEFAULTS: Dict[str, Any] = {
    "beep": True, "lookup_vin": True, "target_loop": 1.0, "extra_per_loop": 4, "slow_every": 60.0,
    "lost_after": 15, "reconnect_tries": 3, "reconnect_wait": 5.0,
}  # fmt: skip

_A_ALERTS, _A_POLL, _A_LINK = "Alerts & lookups", "Polling", "Connection"
# fmt: off
ADVANCED_FIELDS: Tuple[Field, ...] = (
    Field("beep", "Beep on warnings", _A_ALERTS, True, "bool",
          help="3 long beeps = critical, 1 short = warning. The --no-beep option still wins."),
    Field("lookup_vin", "Look up make & model online", _A_ALERTS, True, "bool",
          help="Asks the free NHTSA service; only the VIN is sent. Needs internet."),
    Field("target_loop", "Seconds per reading", _A_POLL, 1.0, "number", "s", 0.25, 10, 0.25,
          "Lower is smoother but the adapter may not keep up."),
    Field("extra_per_loop", "Slower sensors read each cycle", _A_POLL, 4, "int", "", 1, 30, 1,
          "Fast sensors are read every cycle; the rest take turns."),
    Field("slow_every", "Trouble-code check every", _A_POLL, 60, "number", "s", 10, 600, 5,
          "Stored/pending codes and the misfire counters."),
    Field("lost_after", "Link lost after", _A_LINK, 15, "int", "empty cycles", 3, 120, 1,
          "How many cycles in a row without data before it tries to reconnect."),
    Field("reconnect_tries", "Reconnect attempts", _A_LINK, 3, "int", "", 0, 20, 1),
    Field("reconnect_wait", "Wait between attempts", _A_LINK, 5, "number", "s", 1, 60, 1),
)
# fmt: on
TUNING_KEYS = ("target_loop", "extra_per_loop", "slow_every", "lost_after", "reconnect_tries", "reconnect_wait")

# (lower, higher): the first must stay below the second.
ORDERED: Tuple[Tuple[str, str], ...] = (
    ("coolant_cold_c", "coolant_warn_c"),
    ("warmed_up_c", "coolant_warn_c"),
    ("coolant_warn_c", "coolant_crit_c"),
    ("battery_low_running_v", "battery_high_running_v"),
    ("ltft_warn_pct", "ltft_crit_pct"),
    ("catalyst_warn_c", "catalyst_crit_c"),
    ("idle_rpm_min", "idle_rpm_max"),
)

_BY_KEY = {f.key: f for f in THRESHOLD_FIELDS + ADVANCED_FIELDS}
_THRESHOLD_KEYS = {f.key for f in THRESHOLD_FIELDS}
_ADVANCED_KEYS = {f.key for f in ADVANCED_FIELDS}


def _validated(allowed: Set[str], values: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    problems: List[str] = []
    for key, raw in values.items():
        if key not in allowed:
            problems.append(f"Unknown setting '{key}'")
            continue
        try:
            clean[key] = _BY_KEY[key].parse(raw)
        except ValueError as exc:
            problems.append(str(exc))
    if problems:
        raise ConfigError(problems)
    return clean


def _check_order(merged: Dict[str, Any]) -> None:
    problems = [
        f"{_BY_KEY[lo].label} ({merged[lo]:g}) must be below {_BY_KEY[hi].label} ({merged[hi]:g})"
        for lo, hi in ORDERED
        if merged[lo] >= merged[hi]
    ]
    if problems:
        raise ConfigError(problems)


def _lenient(allowed: Set[str], raw: Any) -> Dict[str, Any]:
    """Reading the file back: keep whatever is still valid and silently drop the rest (never crash a session)."""
    out: Dict[str, Any] = {}
    for key, value in (raw if isinstance(raw, dict) else {}).items():
        if key in allowed:
            try:
                out[key] = _BY_KEY[key].parse(value)
            except ValueError:
                continue
    return out


class UserConfig:
    """Read and write `settings.json`. Safe to use from the API thread and the logger thread."""

    def __init__(self, root: Path) -> None:
        self.path = root / SETTINGS_FILE
        self._lock = threading.Lock()

    # ---- file ------------------------------------------------------------------------------
    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        raw_cars = data.get("cars")
        cars: Dict[str, Any] = {}
        for vin, entry in (raw_cars if isinstance(raw_cars, dict) else {}).items():
            cars[str(vin)] = _lenient(_THRESHOLD_KEYS, entry.get("thresholds") if isinstance(entry, dict) else None)
        return {
            "thresholds": _lenient(_THRESHOLD_KEYS, data.get("thresholds")),
            "advanced": _lenient(_ADVANCED_KEYS, data.get("advanced")),
            "cars": cars,
        }

    def _write(self, data: Dict[str, Any]) -> None:
        cars = {vin: {"thresholds": o} for vin, o in data.get("cars", {}).items() if o}
        body = {"thresholds": data.get("thresholds", {}), "advanced": data.get("advanced", {}), "cars": cars}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.path, json.dumps(body, indent=2) + "\n")

    # ---- reading settings --------------------------------------------------------------------
    def threshold_values(self, vin: Optional[str] = None) -> Dict[str, Any]:
        """Effective limits: defaults, then the global overrides, then this car's overrides."""
        with self._lock:
            data = self._read()
        values = asdict(DEFAULT_THRESHOLDS)
        values.update(data.get("thresholds", {}))
        if vin:
            values.update(data.get("cars", {}).get(vin, {}))
        return values

    def thresholds(self, vin: Optional[str] = None) -> Thresholds:
        known = {f.name for f in fields(Thresholds)}
        values = {k: v for k, v in self.threshold_values(vin).items() if k in known}
        return replace(DEFAULT_THRESHOLDS, **values)

    def advanced(self) -> Dict[str, Any]:
        return {**ADVANCED_DEFAULTS, **self.advanced_overrides()}

    def advanced_overrides(self) -> Dict[str, Any]:
        """Only what the user changed (so code that has its own defaults, like tests, is left alone)."""
        with self._lock:
            data = self._read()
        overrides: Dict[str, Any] = data.get("advanced", {})
        return overrides

    def snapshot(self, cars: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Everything the Settings screen needs. `cars` is [{vin, name}] from the garage."""
        with self._lock:
            data = self._read()
        return {
            "schema": {
                "thresholds": [f.to_dict() for f in THRESHOLD_FIELDS],
                "advanced": [f.to_dict() for f in ADVANCED_FIELDS],
            },
            "defaults": asdict(DEFAULT_THRESHOLDS),
            "thresholds": {**asdict(DEFAULT_THRESHOLDS), **data.get("thresholds", {})},
            "advanced_defaults": dict(ADVANCED_DEFAULTS),
            "advanced": {**ADVANCED_DEFAULTS, **data.get("advanced", {})},
            "cars": [
                {**car, "overrides": data.get("cars", {}).get(car["vin"], {})} for car in cars
            ],
        }  # fmt: skip

    # ---- changing settings -------------------------------------------------------------------
    def set_thresholds(self, values: Dict[str, Any], vin: Optional[str] = None) -> None:
        """Replace the overrides for one scope: everywhere (vin=None) or one car. Raises ConfigError."""
        clean = _validated(_THRESHOLD_KEYS, values)
        with self._lock:
            data = self._read() or {"thresholds": {}, "advanced": {}, "cars": {}}
            base = {**asdict(DEFAULT_THRESHOLDS), **(data["thresholds"] if vin else {})}
            overrides = {k: v for k, v in clean.items() if v != base[k]}
            _check_order({**base, **overrides})
            if vin:
                data["cars"][vin] = overrides
            else:
                data["thresholds"] = overrides
            self._write(data)

    def set_advanced(self, values: Dict[str, Any]) -> None:
        clean = _validated(_ADVANCED_KEYS, values)
        with self._lock:
            data = self._read() or {"thresholds": {}, "advanced": {}, "cars": {}}
            data["advanced"] = {k: v for k, v in clean.items() if v != ADVANCED_DEFAULTS[k]}
            self._write(data)

    def reset(self, scope: str, vin: Optional[str] = None) -> None:
        """scope: 'thresholds' (all cars, or one car when vin is given), 'advanced', or 'all'."""
        with self._lock:
            data = self._read() or {"thresholds": {}, "advanced": {}, "cars": {}}
            if scope == "all":
                data = {"thresholds": {}, "advanced": {}, "cars": {}}
            elif scope == "advanced":
                data["advanced"] = {}
            elif scope == "thresholds" and vin:
                data["cars"].pop(vin, None)
            elif scope == "thresholds":
                data["thresholds"] = {}
            else:
                raise ConfigError([f"Unknown reset scope '{scope}'"])
            self._write(data)

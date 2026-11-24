"""Run a used-car check: connect, read the car's own records, sample the engine for a short while, assess.

Strictly read-only, like everything else here. Nothing is written into the garage, so a car you are only
looking at never shows up as one of yours; the report goes in ``<output>/checks``.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Any, Callable, Dict, List, Optional

from obd_dashboard import connection, readers
from obd_dashboard.readers import C
from obd_dashboard.session import NO_CAR_MESSAGE
from obd_dashboard.settings import Settings
from obd_dashboard.types import Sink
from obd_dashboard.usedcar import assess, render_report
from obd_dashboard.userconfig import Thresholds, UserConfig
from obd_dashboard.vin import CarInfo, decode_nhtsa, decode_offline, normalize_vin

log = logging.getLogger(__name__)

CHECK_DIR = "checks"
CHECK_FILE_RE = re.compile(r"^\d{8}_\d{6}_check\.(txt|json)$")
SAMPLE_SECONDS = 20.0
MIN_PLAUSIBLE_V = 5.0
MAX_PLAUSIBLE_V = 20.0


def _sleep(seconds: float) -> bool:
    time.sleep(seconds)
    return False


def check_dir(output_dir: Path) -> Path:
    return output_dir / CHECK_DIR


def check_file(output_dir: Path, name: str) -> Optional[Path]:
    """The saved check file called `name`, or None. Only the exact names this module writes are served."""
    if not CHECK_FILE_RE.match(name):
        return None
    path = check_dir(output_dir) / name
    return path if path.is_file() else None


def _magnitude(value: Any, unit: Optional[str] = None) -> Optional[float]:
    """A plain number from a pint quantity (converted to `unit` if given) or a number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        if unit is not None and hasattr(value, "to"):
            value = value.to(unit)
        return float(getattr(value, "magnitude", value))
    except Exception:  # noqa: BLE001 - an odd unit must not stop a check
        return None


def read_readiness(conn: Any) -> List[Dict[str, Any]]:
    """The self-tests the car runs on its own, and whether each has finished since the last reset."""
    response = readers.query(conn, C.STATUS)
    if response.is_null():
        return []
    tests: List[Dict[str, Any]] = []
    for name in dir(response.value):
        if name.startswith("_") or not name.isupper():
            continue
        item: Any = getattr(response.value, name, None)
        if hasattr(item, "available") and hasattr(item, "complete"):
            tests.append({"name": name, "available": bool(item.available), "complete": bool(item.complete)})
    return tests


def failed_monitors(monitors: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for name, tests in monitors.items():
        for desc, _value, passed in tests:
            if not passed:
                out.append(f"{name.replace('MONITOR_', '').replace('_', ' ').lower()}: {desc}")
    return out


@dataclass
class IdleSample:
    """What the engine did over the sampling window (every list holds one number per reading)."""

    rpm: List[float] = field(default_factory=list)
    speed: List[float] = field(default_factory=list)
    ltft: List[float] = field(default_factory=list)
    stft: List[float] = field(default_factory=list)
    volts_off: List[float] = field(default_factory=list)
    volts_run: List[float] = field(default_factory=list)
    coolant: List[float] = field(default_factory=list)

    def summary(self, running_rpm: float) -> Dict[str, Any]:
        running = [r for r in self.rpm if r > running_rpm]
        engine_on = len(running) * 2 >= len(self.rpm) and bool(running)
        return {
            "samples": len(self.rpm),
            "running": engine_on,
            "moving": bool(self.speed) and max(self.speed) > 5,
            "rpm_min": min(running) if engine_on else None,
            "rpm_max": max(running) if engine_on else None,
            "rpm_mean": fmean(running) if engine_on else None,
            "ltft": fmean(self.ltft) if self.ltft else None,
            "stft": fmean(self.stft) if self.stft else None,
            "volts_off": fmean(self.volts_off) if self.volts_off else None,
            "volts_run": fmean(self.volts_run) if self.volts_run else None,
            "coolant_start": self.coolant[0] if self.coolant else None,
            "coolant_end": self.coolant[-1] if self.coolant else None,
        }


def _volts(conn: Any) -> Optional[float]:
    """Battery voltage from the engine computer, else from the adapter; implausible readings count as none."""
    for cmd in (C.CONTROL_MODULE_VOLTAGE, C.ELM_VOLTAGE):
        if cmd is C.CONTROL_MODULE_VOLTAGE and not conn.supports(cmd):
            continue
        value = readers.parse_value(cmd, readers.query(conn, cmd))[0]
        if isinstance(value, float) and MIN_PLAUSIBLE_V <= value <= MAX_PLAUSIBLE_V:
            return value
    return None


def sample_engine(
    conn: Any,
    *,
    seconds: float,
    running_rpm: float,
    clock: Callable[[], float],
    wait: Callable[[float], bool],
    on_progress: Callable[[float], None] = lambda _left: None,
) -> IdleSample:
    """Read the basics for `seconds`, about four times a second. `wait(s)` returns True if the user cancelled."""
    sample = IdleSample()
    wanted = {"RPM": sample.rpm, "SPEED": sample.speed, "LONG_FUEL_TRIM_1": sample.ltft,
              "SHORT_FUEL_TRIM_1": sample.stft, "COOLANT_TEMP": sample.coolant}  # fmt: skip
    start = clock()
    while clock() - start < seconds:
        tick = clock()
        rpm: Optional[float] = None
        for name, store in wanted.items():
            cmd = getattr(C, name)
            if not conn.supports(cmd):
                continue
            value = readers.parse_value(cmd, readers.query(conn, cmd))[0]
            if isinstance(value, float):
                store.append(value)
                if name == "RPM":
                    rpm = value
        volts = _volts(conn)
        if volts is not None and rpm is not None:
            (sample.volts_run if rpm > running_rpm else sample.volts_off).append(volts)
        on_progress(max(0.0, seconds - (clock() - start)))
        if wait(max(0.0, 0.25 - (clock() - tick))):
            break
    return sample


def collect(
    conn: Any,
    *,
    limits: Thresholds,
    seconds: float = SAMPLE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    wait: Callable[[float], bool] = _sleep,
    on_step: Callable[[str], None] = lambda _msg: None,
    on_progress: Callable[[float], None] = lambda _left: None,
    lookup: Callable[[str], Optional[CarInfo]] = lambda _vin: None,
) -> Dict[str, Any]:
    """Everything the check needs from an open connection, as a plain JSON-safe dict."""
    plan = readers.plan_sensors(conn)
    on_step("Reading the car's records...")
    statics = readers.read_static(conn, plan.statics)
    vin = normalize_vin(statics.get("VIN"))
    info = (lookup(vin) if vin else None) or (decode_offline(vin) if vin else None)
    car = " ".join(str(x) for x in (info.year, info.make, info.model, info.engine) if x) if info else ""
    codes = readers.read_codes(conn)
    monitors = readers.read_monitors(conn, plan.monitors)
    misfire = readers.misfire_counts(monitors).get("total")

    on_step("Listening to the engine...")
    sample = sample_engine(
        conn, seconds=seconds, running_rpm=limits.running_rpm, clock=clock, wait=wait, on_progress=on_progress
    )
    return {
        "vin": vin,
        "car": car,
        "calibration": str(statics.get("CALIBRATION_ID") or "") or None,
        "codes": dict(codes) if codes is not None else None,
        "readiness": read_readiness(conn),
        "since_clear": {
            "distance_km": _magnitude(statics.get("DISTANCE_SINCE_DTC_CLEAR"), "kilometer"),
            "warmups": _magnitude(statics.get("WARMUPS_SINCE_DTC_CLEAR")),
            "minutes": _magnitude(statics.get("TIME_SINCE_DTC_CLEARED"), "minute"),
        },
        "mil_km": _magnitude(statics.get("DISTANCE_W_MIL"), "kilometer"),
        "mil_minutes": _magnitude(statics.get("RUN_TIME_MIL"), "minute"),
        "monitors_read": bool(monitors),
        "monitors_failed": failed_monitors(monitors),
        "misfire_total": misfire,
        "idle": sample.summary(limits.running_rpm),
    }


def save(output_dir: Path, snapshot: Dict[str, Any], result: Dict[str, Any], now: datetime.datetime) -> Dict[str, str]:
    """Write the text report and a JSON copy; returns the file names (not paths: they go to the browser)."""
    folder = check_dir(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = f"{now:%Y%m%d_%H%M%S}"
    text = folder / f"{stamp}_check.txt"
    data = folder / f"{stamp}_check.json"
    text.write_bytes(render_report(snapshot, result, stamp).replace("\n", "\r\n").encode("utf-8"))
    data.write_text(json.dumps({"snapshot": snapshot, "result": result}, indent=2) + "\n", encoding="utf-8")
    return {"report": text.name, "json": data.name}


def run_check(
    settings: Settings,
    sink: Sink,
    stop: Optional[threading.Event] = None,
    *,
    connector: Callable[[Optional[str], int], Any] = connection.open_connection,
    clock: Callable[[], float] = time.monotonic,
    seconds: float = SAMPLE_SECONDS,
    lookup: Callable[[str], Optional[CarInfo]] = decode_nhtsa,
    now: Callable[[], datetime.datetime] = datetime.datetime.now,
) -> Optional[Dict[str, Any]]:
    """Connect, collect, assess, save. Reports through `sink` exactly like a drive session does."""
    stop = stop or threading.Event()
    port = settings.com or connection.find_port()
    if port is None:
        sink.on_status("error", "No serial port found. Plug in the adapter and try again.")
        return None
    sink.on_status("connecting", f"Connecting on {port}...")
    conn = connector(port, settings.baud)
    if conn is None:
        sink.on_status("error", NO_CAR_MESSAGE)
        return None
    try:
        limits = UserConfig(settings.output_dir).thresholds()
        shown = [-1]

        def progress(left: float) -> None:
            if int(left) != shown[0]:  # one update per second is plenty
                shown[0] = int(left)
                sink.on_status("checking", f"Listening to the engine... {int(left) + 1} s left")

        snapshot = collect(
            conn,
            limits=limits,
            seconds=seconds,
            clock=clock,
            wait=stop.wait,
            on_step=lambda msg: sink.on_status("checking", msg),
            on_progress=progress,
            lookup=lookup if settings.lookup_vin else (lambda _vin: None),
        )
    finally:
        conn.close()
    return finish(settings, sink, snapshot, limits, now())


def finish(
    settings: Settings, sink: Sink, snapshot: Dict[str, Any], limits: Thresholds, now: datetime.datetime
) -> Dict[str, Any]:
    result = assess(snapshot, limits)
    files = save(settings.output_dir, snapshot, result, now)
    check = {**result, "snapshot": snapshot, "files": files}
    sink.on_status("finished", "Check finished", {"csv": None, "report": None, "summary": [], "check": check})
    return check

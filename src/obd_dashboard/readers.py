"""Thin, defensive wrappers around python-obd queries (everything here is read-only)."""

from __future__ import annotations

import copy
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import obd

from obd_dashboard.types import Codes

log = logging.getLogger(__name__)
C = obd.commands

# Read every loop.
FAST = [
    "RPM", "SPEED", "ENGINE_LOAD", "COOLANT_TEMP", "THROTTLE_POS",
    "SHORT_FUEL_TRIM_1", "LONG_FUEL_TRIM_1", "SHORT_FUEL_TRIM_2", "LONG_FUEL_TRIM_2",
    "INTAKE_PRESSURE", "TIMING_ADVANCE", "CONTROL_MODULE_VOLTAGE",
]  # fmt: skip
# Read once at the start and once at the end (they change slowly or never).
STATIC = [
    "OBD_COMPLIANCE", "FUEL_TYPE", "WARMUPS_SINCE_DTC_CLEAR", "DISTANCE_SINCE_DTC_CLEAR",
    "TIME_SINCE_DTC_CLEARED", "DISTANCE_W_MIL", "RUN_TIME_MIL", "VIN", "CALIBRATION_ID", "CVN",
]  # fmt: skip
# Never polled in the rotating set (read through dedicated helpers or not useful as a time series).
SKIP = set(STATIC) | {
    "STATUS", "STATUS_DRIVE_CYCLE", "O2_SENSORS", "O2_SENSORS_ALT",
    "FREEZE_DTC", "GET_DTC", "GET_CURRENT_DTC", "CLEAR_DTC",
}  # fmt: skip

MonitorTests = List[Tuple[str, Any, bool]]  # (description, value, passed)


def query(conn: Any, cmd: Any) -> Any:
    """conn.query that never raises: a failed read is just a null response."""
    try:
        return conn.query(cmd)
    except Exception as exc:  # noqa: BLE001 - serial hiccups must not kill a session
        log.debug("query %s failed: %s", getattr(cmd, "name", cmd), exc)
        return obd.OBDResponse()


def parse_value(cmd: Any, response: Any) -> Tuple[Any, Optional[str]]:
    """-> (value, unit). value is a float, a short text token (fuel status) or None."""
    if response.is_null():
        return None, None
    value = response.value
    if cmd.name == "FUEL_STATUS":
        text = next((x for x in value if x), "") if isinstance(value, (tuple, list)) else str(value)
        if "Closed loop" in text:
            return "closed_loop", None
        if "insufficient engine temp" in text:
            return "open_loop_cold", None
        return ("open_loop" if "Open loop" in text else text[:30] or None), None
    try:
        return round(float(value.magnitude), 3), str(value.units)
    except (AttributeError, TypeError, ValueError):
        return None, None


def dtc_list(response: Any) -> List[str]:
    if response.is_null() or response.value is None:
        return []
    return [f"{code} {desc}".strip() for code, desc in response.value]


def read_codes(conn: Any) -> Optional[Codes]:
    """MIL, stored and pending codes, or None if the car did not answer at all.

    "No codes" is an answer (an empty list); a silent car (link lost, ignition off) is not, and must not
    wipe out codes we already know about.
    """
    status, stored, pending = query(conn, C.STATUS), query(conn, C.GET_DTC), query(conn, C.GET_CURRENT_DTC)
    if status.is_null() and stored.is_null() and pending.is_null():
        return None
    return {
        "mil": None if status.is_null() else bool(status.value.MIL),
        "stored": dtc_list(stored),
        "pending": dtc_list(pending),
    }


def read_monitors(conn: Any, cmds: Sequence[Any]) -> Dict[str, MonitorTests]:
    """Mode 06 on-board self-test results."""
    out: Dict[str, MonitorTests] = {}
    for cmd in cmds:
        response = query(conn, cmd)
        if response.is_null():
            continue
        tests = [(t.desc, t.value, t.passed) for t in response.value.tests]
        if tests:  # a car that is shutting down can answer with an empty frame
            out[cmd.name] = tests
    return out


def misfire_counts(monitors: Dict[str, MonitorTests]) -> Dict[str, float]:
    """{'total': n, 'cyl1': n, ...} from the 'last/current driving cycle' misfire tests."""
    counts: Dict[str, float] = {}
    for name, tests in monitors.items():
        if not name.startswith("MONITOR_MISFIRE"):
            continue
        key = "total" if name.endswith("GENERAL") else "cyl" + name.rsplit("_", 1)[1]
        for desc, value, _ in tests:
            if "last/current" in (desc or "").lower():
                with suppress(AttributeError, TypeError, ValueError):
                    counts[key] = float(value.magnitude)
    return counts


def _without_frame_byte(decode: Any) -> Any:
    """Wrap a Mode 1 decoder for a Mode 2 reply, which carries one extra byte (the frame number) after the PID."""

    def wrapped(messages: Any) -> Any:
        fixed = []
        for message in messages:
            clone = copy.copy(message)
            clone.data = bytearray(message.data[:2] + message.data[3:])
            fixed.append(clone)
        return decode(fixed)

    return wrapped


def frame_command(cmd: Any) -> Any:
    """The Mode 2 request done the way SAE J1979 defines it: mode, PID *and frame number* (``0205`` -> ``020500``).

    python-OBD leaves the frame number out. Some ECUs answer anyway; others, like the 2013 Sonata we tested,
    stay silent, and the ones that do answer include the frame byte, which python-OBD's decoders do not expect.
    """
    return obd.OBDCommand(
        cmd.name, cmd.desc, b"02%02X00" % cmd.pid, cmd.bytes + 1, _without_frame_byte(cmd.decode), cmd.ecu, False
    )


def query_frame(conn: Any, cmd: Any) -> Any:
    """Send the frame-number form of a Mode 2 command. ``force`` skips python-OBD's support check, which would
    otherwise refuse the new request because only the old form is in the supported list."""
    try:
        return conn.query(frame_command(cmd), force=True)
    except Exception as exc:  # noqa: BLE001 - same rule as query()
        log.debug("freeze-frame query %s failed: %s", getattr(cmd, "name", cmd), exc)
        return obd.OBDResponse()


# With no stored code there is no freeze frame and every PID answers NO DATA; no need to ask them all.
FREEZE_GIVE_UP_AFTER = 3


def freeze_frame(conn: Any) -> List[str]:
    cmds = sorted(
        (c for c in conn.supported_commands if c.mode == 2 and c.pid is not None and "PIDS_" not in c.name),
        key=lambda c: c.pid or 0,
    )
    lines: List[str] = []
    misses = 0
    for cmd in cmds:
        response = query_frame(conn, cmd)
        if response.is_null():
            misses += 1
            if not lines and misses >= FREEZE_GIVE_UP_AFTER:
                break
            continue
        misses = 0
        lines.append(f"    {cmd.name:<32} {response.value}")
    return lines or ["    (car returned no freeze-frame data)"]


# python-obd decodes these with .strip(b"\x00\x01\x02\\x00...") which also eats a trailing '0', '1', '2' or 'x'
# (a VIN ending in 1 comes back one character short), so we rebuild the text from the raw frame instead.
RAW_TEXT_PIDS = {"VIN", "CALIBRATION_ID"}


def raw_text(response: Any) -> Optional[str]:
    """Printable ASCII from the raw Mode 09 payload, or None if the raw frame is unavailable."""
    try:
        data = bytes(response.messages[0].data[2:])
    except (AttributeError, IndexError, TypeError):
        return None
    text = "".join(chr(b) for b in data if 32 <= b < 127).strip()
    return text or None


def read_static(conn: Any, cmds: Sequence[Any]) -> Dict[str, Any]:
    """Slow-changing car info (VIN, fuel type, counters). Byte strings are decoded to text."""
    out: Dict[str, Any] = {}
    for cmd in cmds:
        response = query(conn, cmd)
        if response.is_null():
            continue
        value = response.value
        if cmd.name in RAW_TEXT_PIDS:
            value = raw_text(response) or value
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("ascii", errors="ignore")
        out[cmd.name] = value
    return out


def read_counters(conn: Any, cmds: Sequence[Any]) -> Dict[str, Any]:
    """Like read_static but only numeric counters (skips VIN/CVN text) - used for the end-of-run diff."""
    return {
        name: value for name, value in read_static(conn, cmds).items() if not isinstance(value, (bytes, bytearray, str))
    }


@dataclass
class SensorPlan:
    fast: List[Any] = field(default_factory=list)
    rest: List[Any] = field(default_factory=list)
    statics: List[Any] = field(default_factory=list)
    monitors: List[Any] = field(default_factory=list)

    @property
    def polled(self) -> List[Any]:
        return self.fast + self.rest


def plan_sensors(conn: Any) -> SensorPlan:
    """Work out which sensors this particular car supports and how often to read each."""
    supported = conn.supported_commands
    fast = [c for n in FAST if (c := getattr(C, n, None)) is not None and conn.supports(c)]
    rest = sorted(
        (
            c
            for c in supported
            if c.mode == 1 and c.name not in SKIP and c not in fast and not c.name.startswith(("PIDS_", "MIDS_"))
        ),
        key=lambda c: c.pid or 0,
    )
    statics = [c for n in STATIC if (c := getattr(C, n, None)) is not None and conn.supports(c)]
    monitors = sorted((c for c in supported if c.name.startswith("MONITOR_")), key=lambda c: c.name)
    return SensorPlan(fast, rest, statics, monitors)


def car_commands(conn: Any) -> List[Any]:
    """The commands the car itself supports, sorted by mode and PID.

    python-obd also lists its two adapter commands (ELM_VERSION, ELM_VOLTAGE) in `supported_commands`.
    They have no mode and no PID, so they are left out here.
    """
    cmds = [c for c in conn.supported_commands if c.mode is not None]
    return sorted(cmds, key=lambda c: (c.mode, c.pid or 0, c.name))


def fmt_supported(conn: Any) -> List[str]:
    """Every command the car says it supports (its own PID bitmasks), by mode, e.g. '01 0C RPM'."""
    cmds = car_commands(conn)
    return [f"  {c.mode:02d} {(c.pid or 0):02X}  {c.name:<30} {c.desc}" for c in cmds] or ["  (none reported)"]


def fmt_monitors(monitors: Dict[str, MonitorTests]) -> List[str]:
    lines: List[str] = []
    for name, tests in monitors.items():
        lines.append(f"  {name}")
        lines += [f"      {d}: {v} [{'PASS' if ok else 'FAIL'}]" for d, v, ok in tests]
    return lines or ["  (none reported)"]

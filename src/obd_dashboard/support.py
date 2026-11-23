"""`obd-dashboard support`: write a small anonymous JSON file for bug and compatibility reports.

It answers the questions every "doesn't work on my car" issue starts with: which adapter, which protocol,
which sensors does the car list and which of them actually answer. It never includes the full VIN, serial
numbers, locations or any logged driving data (see NOTES).
"""

from __future__ import annotations

import datetime
import json
import platform
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import obd
from serial.tools import list_ports

from obd_dashboard import __version__
from obd_dashboard.connection import link_info, open_connection
from obd_dashboard.readers import SensorPlan, car_commands, plan_sensors, query, query_frame, raw_text, read_codes
from obd_dashboard.vin import WMI_MAKES, model_year, normalize_vin

SCHEMA = 1
ISSUES_URL = "https://github.com/falcon883/obd-dashboard/issues/new/choose"
NOTES = [
    "Contains: app/Python/OS versions, adapter and protocol, the sensors the car lists and whether each answers, "
    "and any trouble codes.",
    "Left out on purpose: the full VIN (only the 3-character maker code and model year), serial numbers, "
    "your location, and every logged value.",
]

Opener = Callable[[Optional[str], int], Optional[Any]]


def _ports() -> List[Dict[str, Any]]:
    """Serial ports as the OS describes them, without serial numbers or hardware paths."""
    return [
        {
            "device_type": (p.description or "").strip() or None,
            "vid": f"{p.vid:04X}" if p.vid is not None else None,
            "pid": f"{p.pid:04X}" if p.pid is not None else None,
        }
        for p in list_ports.comports()
    ]


def _text(conn: Any, name: str) -> Optional[str]:
    cmd = getattr(obd.commands, name, None)
    if cmd is None:
        return None
    response = query(conn, cmd)
    return None if response.is_null() else str(response.value)


def _vehicle(conn: Any) -> Dict[str, Any]:
    response = query(conn, obd.commands.VIN) if conn.supports(obd.commands.VIN) else None
    vin = None
    if response is not None and not response.is_null():
        value = response.value
        text = value.decode("ascii", "ignore") if isinstance(value, (bytes, bytearray)) else str(value)
        vin = normalize_vin(raw_text(response) or text)
    return {
        "model_year": model_year(vin) if vin else None,
        "vin_maker_code": vin[:3] if vin else None,
        "maker_guess": WMI_MAKES.get(vin[:3]) if vin else None,
        "fuel_type": _text(conn, "FUEL_TYPE"),
        "obd_standard": _text(conn, "OBD_COMPLIANCE"),
    }


def _supported(conn: Any, plan: SensorPlan) -> List[Dict[str, Any]]:
    """Every command the car lists, and for the live sensors whether a real read returned data."""
    live = {c.name for c in plan.polled}
    out = []
    for cmd in car_commands(conn):
        entry: Dict[str, Any] = {"mode": cmd.mode, "pid": f"{(cmd.pid or 0):02X}", "name": cmd.name}
        if cmd.name in live:
            entry["answers"] = not query(conn, cmd).is_null()
        out.append(entry)
    return out


def _raw_replies(response: Any) -> List[str]:
    raw: List[str] = []
    for message in getattr(response, "messages", None) or []:
        try:
            raw.append(str(message.raw()))
        except Exception:  # noqa: BLE001 - a diagnostic extra must never break the report
            continue
    return raw


def _freeze_frame_probe(conn: Any) -> Optional[Dict[str, Any]]:
    """Ask for one freeze-frame value both ways and keep the raw replies, to see how this car wants to be asked.

    ``answered``/``raw`` are the plain python-OBD request (``0205``); ``with_frame_number`` is the SAE form
    (``020500``) that the app now uses.
    """
    cmd = next((c for c in car_commands(conn) if c.mode == 2 and c.pid is not None and "PIDS_" not in c.name), None)
    if cmd is None:
        return None
    plain = query(conn, cmd)
    framed = query_frame(conn, cmd)
    return {
        "command": cmd.name,
        "answered": not plain.is_null(),
        "raw": _raw_replies(plain),
        "with_frame_number": {"answered": not framed.is_null(), "raw": _raw_replies(framed)},
    }


def collect(conn: Any) -> Dict[str, Any]:
    """Everything we can say about the adapter and the car, from an open connection."""
    plan = plan_sensors(conn)
    port, baud = link_info(conn, "", 0)
    voltage = _text(conn, "ELM_VOLTAGE")
    return {
        "link": {
            "connected": True,
            "baud": baud or None,
            "protocol": conn.protocol_name(),
            "status": conn.status(),
            "elm_version": _text(conn, "ELM_VERSION"),
            "adapter_voltage": voltage,
        },
        "vehicle": _vehicle(conn),
        "codes": read_codes(conn),
        "freeze_frame_probe": _freeze_frame_probe(conn),
        "supported": _supported(conn, plan),
        "monitors": [c.name for c in plan.monitors],
    }


def report_base(now: datetime.datetime) -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "created": now.isoformat(timespec="seconds"),
        "app_version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "serial_ports": _ports(),
        "notes": NOTES,
    }


def run(
    port: Optional[str] = None,
    baud: int = 0,
    out: Optional[Path] = None,
    *,
    opener: Opener = open_connection,
    now: Callable[[], datetime.datetime] = datetime.datetime.now,
) -> int:
    started = now()
    report = report_base(started)
    path = out or Path(f"obd-support-{started:%Y%m%d_%H%M%S}.json")
    print("Looking for the adapter and the car (ignition ON, engine running or not)...")
    conn = opener(port, baud)
    code = 0
    if conn is None:
        report["link"] = {"connected": False}
        print("Could not connect. The file still lists your serial ports, which helps to work out why.")
        code = 1
    else:
        try:
            report.update(collect(conn))
        finally:
            conn.close()
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {path.resolve()}")
    for line in NOTES:
        print(f"  {line}")
    print(f"\nOpen the file and look it over, then attach it to a new issue: {ISSUES_URL}")
    return code

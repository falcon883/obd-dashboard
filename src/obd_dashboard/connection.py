"""Finding the adapter: serial port discovery, baud probing and opening the OBD link."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, List, Optional, Tuple

import obd
import serial
from serial.tools import list_ports

log = logging.getLogger(__name__)

CH340_VID = 0x1A86
# 38400 is what ELM327 v1.5 clones normally use; the rest are tried in order of likelihood.
BAUDS: Tuple[int, ...] = (38400, 115200, 9600, 57600, 230400)


def candidate_ports(lister: Callable[[], Any] = list_ports.comports) -> List[str]:
    """CH340 adapters first, then any other serial port."""
    ports = list(lister())
    ch340 = [p.device for p in ports if "CH340" in (p.description or "").upper() or p.vid == CH340_VID]
    return ch340 + [p.device for p in ports if p.device not in ch340]


def find_port() -> Optional[str]:
    ports = candidate_ports()
    return ports[0] if ports else None


def probe_baud(
    port: str,
    preferred: Optional[int] = None,
    *,
    open_serial: Callable[..., Any] = serial.Serial,
    settle: float = 1.2,
) -> Optional[int]:
    """Return the baud rate at which an ELM327 answers on `port`, or None."""
    order = ([preferred] if preferred else []) + [b for b in BAUDS if b != preferred]
    for baud in order:
        try:
            with open_serial(port, baud, timeout=1.2, write_timeout=1) as s:
                s.reset_input_buffer()
                s.write(b"\r")  # flush any half-typed command
                time.sleep(settle / 6)
                s.reset_input_buffer()
                s.write(b"ATZ\r")
                time.sleep(settle)
                reply = s.read(s.in_waiting or 64).decode("ascii", "ignore").upper()
        except (serial.SerialException, OSError) as exc:
            log.debug("probe %s @ %s failed: %s", port, baud, exc)
            continue
        if "ELM" in reply or ">" in reply:  # '>' is the ELM327 prompt
            log.info("ELM327 answered on %s at %s baud", port, baud)
            return baud
    return None


def open_connection(
    port: Optional[str],
    baud: int = 0,
    *,
    obd_factory: Callable[..., Any] = obd.OBD,
    probe: Callable[..., Optional[int]] = probe_baud,
) -> Optional[Any]:
    """Open a python-obd link. `baud=0` auto-detects the baud and, if `port` fails, tries other ports."""
    ports = [port] if port else []
    if not baud:
        ports += [p for p in candidate_ports() if p != port]
    for pt in ports:
        found = baud or probe(pt)
        log.info("Connecting on %s (%s baud)...", pt, found or "auto")
        for attempt in (found, None) if found else (None,):  # None = python-obd's own scan
            conn = obd_factory(pt, baudrate=attempt, fast=False, timeout=10)
            if conn.is_connected():
                return conn
            log.warning("  %s", conn.status())
            conn.close()
    return None


def link_info(conn: Any, port: str, baud: int) -> Tuple[str, int]:
    """Report the port/baud actually in use (python-obd keeps the serial object private)."""
    try:
        port = conn.port_name() or port
        baud = conn.interface._ELM327__port.baudrate
    except Exception:  # noqa: BLE001 - purely informational
        pass
    return port, baud

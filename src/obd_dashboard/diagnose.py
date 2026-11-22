"""`obd-dashboard test`: talk to the adapter directly and print the raw replies."""

from __future__ import annotations

import time
from typing import Optional

import serial

from obd_dashboard.connection import BAUDS, find_port, probe_baud

CHECKS = [
    ("Echo off", "ATE0", 1.0),
    ("Battery voltage", "ATRV", 1.0),
    ("Auto protocol", "ATSP0", 1.0),
    ("Supported PIDs", "0100", 8.0),
    ("Protocol used", "ATDP", 1.0),
    ("RPM", "010C", 2.0),
    ("Coolant temp", "0105", 2.0),
]


def _send(s: serial.Serial, cmd: str, wait: float) -> str:
    s.reset_input_buffer()
    s.write((cmd + "\r").encode())
    time.sleep(wait)
    reply: str = s.read(s.in_waiting or 1).decode(errors="ignore")
    return reply.replace("\r", " ").strip()


def run(port: Optional[str] = None, baud: int = 0) -> int:
    port = port or find_port()
    if port is None:
        print("No serial port found. Re-plug the USB adapter and check Device Manager.")
        return 1
    print(f"Port {port}: looking for the adapter ({', '.join(map(str, BAUDS))} baud)...")
    found = baud or probe_baud(port)
    if not found:
        print("No ELM327 reply at any baud. Re-plug the adapter and close any other app using the port.")
        return 1
    print(f"Adapter OK at {found} baud. Testing the car (ignition must be ON)...\n")
    try:
        with serial.Serial(port, found, timeout=2) as s:
            for label, cmd, wait in CHECKS:
                print(f"{label:<16} {cmd:<6} -> {_send(s, cmd, wait)}")
    except serial.SerialException as exc:
        print(f"Cannot use {port}: {exc}\n(Close any other app using it.)")
        return 1
    return 0

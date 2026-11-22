from __future__ import annotations

from types import SimpleNamespace

import serial

from obd_dashboard import connection


def port(device, description="", vid=None):
    return SimpleNamespace(device=device, description=description, vid=vid)


def test_ch340_ports_come_first():
    ports = [port("COM1", "Bluetooth link"), port("COM4", "USB-SERIAL CH340 (COM4)", 0x1A86), port("COM2", "Modem")]
    assert connection.candidate_ports(lambda: ports) == ["COM4", "COM1", "COM2"]


def test_vid_alone_identifies_ch340():
    assert connection.candidate_ports(lambda: [port("COM1"), port("COM9", "USB Serial", 0x1A86)])[0] == "COM9"


class FakeSerial:
    """Answers like an ELM327 only at `good_baud`; raises for ports that cannot be opened."""

    good_baud = 38400
    opened: list[int] = []

    def __init__(self, device, baud, **_kw):
        if device == "BUSY":
            raise serial.SerialException("access denied")
        type(self).opened.append(baud)
        self.baud, self.in_waiting, self._buf = baud, 0, b""

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def reset_input_buffer(self):
        self._buf, self.in_waiting = b"", 0

    def write(self, data):
        if data == b"ATZ\r" and self.baud == self.good_baud:
            self._buf = b"ATZ\r\rELM327 v1.5\r\r>"
            self.in_waiting = len(self._buf)

    def read(self, n):
        out, self._buf, self.in_waiting = self._buf[:n], b"", 0
        return out


def test_probe_finds_the_baud_that_answers():
    FakeSerial.opened, FakeSerial.good_baud = [], 115200
    assert connection.probe_baud("COM4", open_serial=FakeSerial, settle=0.0) == 115200
    assert FakeSerial.opened == [38400, 115200]  # stops at the first hit


def test_probe_tries_the_preferred_baud_first():
    FakeSerial.opened, FakeSerial.good_baud = [], 9600
    assert connection.probe_baud("COM4", preferred=9600, open_serial=FakeSerial, settle=0.0) == 9600
    assert FakeSerial.opened == [9600]


def test_probe_returns_none_when_nothing_answers_or_port_is_busy():
    FakeSerial.good_baud = 1
    assert connection.probe_baud("COM4", open_serial=FakeSerial, settle=0.0) is None
    assert connection.probe_baud("BUSY", open_serial=FakeSerial, settle=0.0) is None


class FakeObd:
    def __init__(self, ok_on):
        self.ok_on, self.calls = ok_on, []

    def __call__(self, port, baudrate=None, **_kw):
        self.calls.append((port, baudrate))
        ok = port == self.ok_on
        return SimpleNamespace(is_connected=lambda: ok, status=lambda: "Not Connected", close=lambda: None, port=port)


def test_open_connection_uses_probed_baud():
    factory = FakeObd("COM4")
    conn = connection.open_connection("COM4", 0, obd_factory=factory, probe=lambda _p: 38400)
    assert conn.port == "COM4" and factory.calls == [("COM4", 38400)]


def test_open_connection_falls_back_to_python_obd_scan_then_other_ports(monkeypatch):
    monkeypatch.setattr(connection, "candidate_ports", lambda: ["COM4", "COM7"])
    factory = FakeObd("COM7")
    conn = connection.open_connection("COM4", 0, obd_factory=factory, probe=lambda p: 38400 if p == "COM4" else None)
    assert conn.port == "COM7"
    assert factory.calls == [("COM4", 38400), ("COM4", None), ("COM7", None)]


def test_explicit_baud_does_not_wander_to_other_ports(monkeypatch):
    monkeypatch.setattr(connection, "candidate_ports", lambda: ["COM4", "COM7"])
    factory = FakeObd("COM7")
    assert connection.open_connection("COM4", 38400, obd_factory=factory, probe=lambda _p: None) is None
    assert {p for p, _ in factory.calls} == {"COM4"}

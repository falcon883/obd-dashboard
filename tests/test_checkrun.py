from __future__ import annotations

import datetime
import json
import threading
from typing import Any

import obd
import pytest

from obd_dashboard import checkrun
from obd_dashboard.checkrun import check_file, collect, read_readiness, run_check, sample_engine
from obd_dashboard.userconfig import DEFAULT_THRESHOLDS
from obd_dashboard.vin import CarInfo
from tests.conftest import RecordingSink
from tests.fakes import FakeCar, R

C = obd.commands
Q = obd.Unit.Quantity


class Probe:
    def __init__(self, available: bool, complete: bool) -> None:
        self.available, self.complete = available, complete


class FullStatus:
    MIL = False
    MISFIRE_MONITORING = Probe(True, True)
    CATALYST_MONITORING = Probe(True, False)
    EGR_VVT_SYSTEM_MONITORING = Probe(False, False)
    DTC_count = 0
    ignition_type = "spark"

    def __init__(self) -> None:
        self.lowercase_noise = 1


class CheckCar(FakeCar):
    """A FakeCar that also knows the 'since reset' counters, a full STATUS and a steady idle."""

    def __init__(self, *, engine_on: bool = True, ltft: float = 3.1, distance: float = 5000.0) -> None:
        super().__init__()
        self.supported_commands = self.supported_commands | {C.DISTANCE_SINCE_DTC_CLEAR}
        self.engine_on, self.ltft, self.distance = engine_on, ltft, distance

    def supports(self, cmd: Any) -> bool:
        return cmd in self.supported_commands

    def query(self, cmd: Any, force: bool = False) -> Any:
        name = cmd.name
        if name == "VIN":
            return R(bytearray(b"5NPE24AF3GH283081"))
        if name == "STATUS":
            return R(FullStatus())
        if name == "RPM":
            self.n += 1
            return R(Q(750 if self.engine_on else 0, "rpm"))
        if name == "SPEED":
            return R(Q(0, "kph"))
        if name == "COOLANT_TEMP":
            return R(Q(90, "celsius"))
        if name == "LONG_FUEL_TRIM_1":
            return R(Q(self.ltft, "percent"))
        if name == "CONTROL_MODULE_VOLTAGE":
            return R(Q(14.2 if self.engine_on else 12.4, "volt"))
        if name == "DISTANCE_SINCE_DTC_CLEAR":
            return R(Q(self.distance, "kilometer"))
        if name == "GET_DTC":
            return R([])
        return super().query(cmd, force)


class Clock:
    """Time that only moves when the code under test waits, so tests do not sleep."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def wait(self, seconds: float) -> bool:
        self.t += max(seconds, 0.01)
        return False


def test_readiness_reads_only_the_self_test_objects():
    car = CheckCar()
    assert read_readiness(car) == [
        {"name": "CATALYST_MONITORING", "available": True, "complete": False},
        {"name": "EGR_VVT_SYSTEM_MONITORING", "available": False, "complete": False},
        {"name": "MISFIRE_MONITORING", "available": True, "complete": True},
    ]


def test_readiness_is_empty_when_the_car_does_not_answer():
    class Mute(FakeCar):
        def query(self, cmd: Any, force: bool = False) -> Any:
            return obd.OBDResponse()

    assert read_readiness(Mute()) == []


def test_sampling_splits_engine_off_and_running_voltage():
    clock = Clock()
    on = sample_engine(CheckCar(), seconds=2, running_rpm=400, clock=clock, wait=clock.wait)
    assert on.volts_run and not on.volts_off and on.summary(400)["running"] is True
    clock = Clock()
    off = sample_engine(CheckCar(engine_on=False), seconds=2, running_rpm=400, clock=clock, wait=clock.wait)
    summary = off.summary(400)
    assert off.volts_off and not off.volts_run and summary["running"] is False and summary["rpm_mean"] is None


def test_sampling_stops_when_cancelled():
    sample = sample_engine(CheckCar(), seconds=60, running_rpm=400, clock=Clock(), wait=lambda _s: True)
    assert len(sample.rpm) == 1


def test_collect_builds_a_complete_json_safe_snapshot():
    clock = Clock()
    steps: list[str] = []
    snap = collect(
        CheckCar(), limits=DEFAULT_THRESHOLDS, seconds=3, clock=clock, wait=clock.wait, on_step=steps.append,
        lookup=lambda vin: CarInfo(vin, year=2016, make="Hyundai", model="Sonata", engine="2.4 L 4-cyl"),
    )  # fmt: skip
    json.dumps(snap)  # everything is plain data
    assert snap["vin"] == "5NPE24AF3GH283081" and snap["car"] == "2016 Hyundai Sonata 2.4 L 4-cyl"
    assert snap["codes"] == {"mil": False, "stored": [], "pending": []}
    assert snap["since_clear"]["distance_km"] == 5000.0 and snap["since_clear"]["warmups"] == 42.0
    assert (
        snap["idle"]["running"] is True
        and snap["idle"]["ltft"] == 3.1
        and snap["idle"]["volts_run"] == pytest.approx(14.2)
    )
    assert len(snap["readiness"]) == 3
    assert snap["monitors_failed"] == ["evap 150: Unknown"]  # the fake car's one failing Mode 06 test
    assert steps == ["Reading the car's records...", "Listening to the engine..."]


def test_collect_falls_back_to_the_vin_when_the_lookup_is_offline():
    clock = Clock()
    snap = collect(CheckCar(), limits=DEFAULT_THRESHOLDS, seconds=1, clock=clock, wait=clock.wait)
    assert snap["car"].startswith("2016 Hyundai")  # year straight from the VIN, no internet needed


def run(tmp_path, settings, car, **kwargs):
    clock = Clock()
    sink = RecordingSink()
    result = run_check(
        settings, sink, threading.Event(), connector=lambda _p, _b: car, clock=clock, seconds=2,
        lookup=lambda _v: None, now=lambda: datetime.datetime(2026, 1, 2, 3, 4, 5), **kwargs,
    )  # fmt: skip
    return sink, result


def test_run_check_reports_progress_then_a_finished_result_and_writes_files(settings, monkeypatch):
    clock_holder: list[Clock] = []
    real = checkrun.sample_engine

    def fast(conn, **kw):  # let the run use our fake time
        clock = Clock()
        clock_holder.append(clock)
        return real(conn, **{**kw, "clock": clock, "wait": clock.wait})

    monkeypatch.setattr(checkrun, "sample_engine", fast)
    car = CheckCar(distance=20.0)
    sink = RecordingSink()
    result = run_check(
        settings.__class__(**{**settings.__dict__, "com": "FAKE0"}), sink, threading.Event(),
        connector=lambda _p, _b: car, seconds=3, lookup=lambda _v: None,
        now=lambda: datetime.datetime(2026, 1, 2, 3, 4, 5),
    )  # fmt: skip
    assert car.closed
    assert sink.states[0] == "connecting" and sink.states[-1] == "finished" and "checking" in sink.states
    check = sink.statuses[-1][2]["check"]
    assert check == result and check["verdict"] in {"look", "flags"}  # 20 km since reset
    folder = settings.output_dir / "checks"
    assert sorted(p.name for p in folder.iterdir()) == ["20260102_030405_check.json", "20260102_030405_check.txt"]
    assert check["files"] == {"report": "20260102_030405_check.txt", "json": "20260102_030405_check.json"}
    raw = (folder / "20260102_030405_check.txt").read_bytes()
    assert b"\r\n" in raw and b"\r\r" not in raw  # Windows line endings, written once
    assert not (settings.output_dir / "cars").exists()  # a car you are looking at is not added to the garage


def test_run_check_reports_a_missing_adapter(settings):
    sink = RecordingSink()
    out = run_check(settings.__class__(**{**settings.__dict__, "com": "FAKE0"}), sink, connector=lambda _p, _b: None)
    assert out is None and sink.states == ["connecting", "error"]


def test_run_check_with_no_port_says_so(settings, monkeypatch):
    monkeypatch.setattr(checkrun.connection, "find_port", lambda: None)
    sink = RecordingSink()
    assert run_check(settings, sink, connector=lambda _p, _b: None) is None
    assert sink.states == ["error"] and "No serial port" in sink.statuses[0][1]


def test_check_file_serves_only_the_names_a_check_writes(tmp_path):
    folder = tmp_path / "checks"
    folder.mkdir()
    (folder / "20260102_030405_check.txt").write_text("x")
    (folder / "notes.txt").write_text("secret")
    assert check_file(tmp_path, "20260102_030405_check.txt") == folder / "20260102_030405_check.txt"
    for bad in (
        "notes.txt",
        "../checks/20260102_030405_check.txt",
        "20260102_030405_check.exe",
        "20260102_030406_check.txt",
    ):
        assert check_file(tmp_path, bad) is None

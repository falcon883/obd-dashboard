from __future__ import annotations

import csv
import json
import threading
import time
from dataclasses import replace
from pathlib import Path

import obd

from obd_dashboard.garage import Garage
from obd_dashboard.session import Session
from obd_dashboard.vin import CarInfo
from tests.conftest import RecordingSink
from tests.fakes import FakeCar, Q, R


def run_session(settings, car, rows=30, connector=None):
    stop = threading.Event()
    sink = RecordingSink(stop, rows)
    session = Session(
        settings, sink, stop,
        connector=connector or (lambda _port, _baud: car),
        notifier=lambda level: sink.events.append(("beep", level)),
    )  # fmt: skip
    session.run()
    return session, sink


def test_full_session_writes_files_and_reports_everything(settings):
    car = FakeCar()
    settings = replace(settings, com="FAKE0", baud=38400)
    session, sink = run_session(settings, car, rows=30)

    assert sink.states == ["connecting", "connected", "finished"]
    assert car.closed
    assert len(sink.rows) == 30 and sink.infos[0]["port"] == "FAKE0"
    assert sink.infos[0]["static"]["VIN"] == "1M8GDM9AXKP042781"

    # alerts: coolant passes 102C and a stored code appears; both are transition-based (raised once)
    alerts = [e for e in sink.events if isinstance(e, dict)]
    messages = [a["msg"] for a in alerts]
    assert sum("Coolant running hot" in m for m in messages) == 1
    assert any("P0300" in m for m in messages)
    assert ("beep", "CRIT") in sink.events and ("beep", "WARN") in sink.events

    # files
    result = sink.statuses[-1][2]
    rows = list(csv.DictReader(Path(result["csv"]).read_text().splitlines()))
    assert len(rows) == 30 and "coolant_temp_c" in rows[0] and "rpm" in rows[0]
    report = Path(result["report"]).read_text()
    assert "=== SUPPORTED COMMANDS" in report and "01 0C  RPM" in report
    assert "=== SUMMARY ===" in report and "CRITICAL" in report and "Freeze frame" in report
    assert session.worst == 2


def test_row_payload_matches_what_the_frontend_expects(settings):
    _, sink = run_session(replace(settings, com="FAKE0"), FakeCar(), rows=3)
    row = sink.rows[-1]
    assert set(row) == {"t", "ts", "values", "alerts", "codes", "misfire", "misfire0", "warm", "start_cool"}
    assert {"RPM", "SPEED", "COOLANT_TEMP", "battery_v"} <= set(row["values"])
    assert set(row["codes"]) == {"mil", "stored", "pending"}


def test_error_when_the_car_cannot_be_reached(settings):
    _, sink = run_session(replace(settings, com="COM9"), None, connector=lambda _p, _b: None)
    assert sink.states == ["connecting", "error"] and "Could not talk to the car" in sink.statuses[-1][1]
    assert not settings.output_dir.exists()  # no files for a session that never started


def test_error_when_no_serial_port_exists(settings, monkeypatch):
    monkeypatch.setattr("obd_dashboard.session.connection.find_port", lambda: None)
    sink = RecordingSink()
    Session(settings, sink, threading.Event()).run()
    assert sink.states == ["error"] and "No serial port" in sink.statuses[0][1]


def test_lost_link_reconnects_and_keeps_logging(settings):
    cars = [FakeCar(dead_after=8), FakeCar()]
    calls = []

    def connector(port, baud):
        calls.append((port, baud))
        return cars[len(calls) - 1] if len(calls) <= 2 else None

    _, sink = run_session(replace(settings, com="FAKE0", baud=38400), None, rows=40, connector=connector)
    assert "lost" in sink.states and sink.states.count("connected") == 2
    assert sink.states[-1] == "finished"
    assert cars[0].closed and cars[1].closed


def test_gives_up_after_failed_reconnects_but_still_writes_summary(settings):
    car = FakeCar(dead_after=8)
    attempts = []

    def connector(_p, _b):
        attempts.append(1)
        return car if len(attempts) == 1 else None

    _, sink = run_session(replace(settings, com="FAKE0", baud=38400), None, rows=1000, connector=connector)
    assert sink.states[-1] == "finished" and len(attempts) == 1 + settings.tuning.reconnect_tries
    assert "=== SUMMARY ===" in Path(sink.statuses[-1][2]["report"]).read_text()


class CodedCar(FakeCar):
    """Has a stored code from the first query on, like the friend's 2013 Sonata with P0456."""

    def query(self, cmd):
        response = super().query(cmd)
        if cmd.name == "GET_DTC" and not response.is_null():
            return R([("P0456", "Evaporative Emission System Leak Detected (very small leak)")])
        return response


class VoltCar(FakeCar):
    """Reports the given module and adapter voltages."""

    def __init__(self, module, adapter):
        super().__init__()
        self.volts = {"CONTROL_MODULE_VOLTAGE": module, "ELM_VOLTAGE": adapter}

    def query(self, cmd):
        if cmd.name in self.volts:
            return R(Q(self.volts[cmd.name], "volt"))
        return super().query(cmd)


def _battery_values(settings, car):
    _, sink = run_session(replace(settings, com="FAKE0", baud=38400), car, rows=6)
    return [row["values"]["battery_v"] for row in sink.rows], sink


def test_battery_uses_the_adapter_when_the_computer_reports_zero_volts(settings):
    """Seen on the real car: the computer reads 0.0 V for a few seconds around key-off."""
    values, sink = _battery_values(settings, VoltCar(module=0.0, adapter=12.7))
    assert set(values) == {12.7}
    assert not any(isinstance(e, dict) and "battery" in e["msg"].lower() for e in sink.events)


def test_battery_reading_is_empty_when_neither_source_is_plausible(settings):
    values, sink = _battery_values(settings, VoltCar(module=0.0, adapter=0.1))
    assert set(values) == {None}
    assert not any(isinstance(e, dict) and "battery" in e["msg"].lower() for e in sink.events)


def test_codes_and_failures_stay_in_the_report_when_the_car_goes_quiet(settings):
    """Real report: 'Codes at end: none' after ignition off, although P0456 and a failed EVAP test were showing."""
    car = CodedCar(dead_after=8)
    attempts = []

    def connector(_p, _b):
        attempts.append(1)
        return car if len(attempts) == 1 else None

    _, sink = run_session(replace(settings, com="FAKE0", baud=38400), None, rows=1000, connector=connector)
    report_path = Path(sink.statuses[-1][2]["report"])
    report = report_path.read_text()
    assert "Codes at end: stored ['P0456" in report and "last known" in report
    assert "Mode 06 failures (last known, car stopped answering): MONITOR_EVAP_150" in report
    assert "(the car had stopped answering)" in report
    summary = json.loads(report_path.with_name(report_path.name.replace("_report.txt", "_summary.json")).read_text())
    assert summary["stored_codes"] == ["P0456 Evaporative Emission System Leak Detected (very small leak)"]


def test_a_session_that_ends_normally_reports_the_real_end_state(settings):
    _, sink = run_session(replace(settings, com="FAKE0", baud=38400), CodedCar(), rows=5)
    report = Path(sink.statuses[-1][2]["report"]).read_text()
    assert "last known" not in report and "Mode 06 failures at end:" in report


def test_a_crashing_subscriber_never_stops_the_logger(settings):
    class Bad(RecordingSink):
        def on_row(self, row):
            super().on_row(row)
            raise ValueError("subscriber bug")

    stop = threading.Event()
    sink = Bad(stop, 5)
    Session(replace(settings, com="FAKE0"), sink, stop, connector=lambda _p, _b: FakeCar()).run()
    assert len(sink.rows) == 5 and sink.states[-1] == "finished"


def test_session_never_sends_clear_dtc(settings):
    sent = []

    class Spy(FakeCar):
        def query(self, cmd):
            sent.append(cmd.name)
            return super().query(cmd)

    run_session(replace(settings, com="FAKE0"), Spy(), rows=10)
    assert sent and "CLEAR_DTC" not in sent


def test_files_go_into_the_cars_folder_with_profile_and_summary(settings):
    settings = replace(settings, com="FAKE0", baud=38400)
    session, sink = run_session(settings, FakeCar(), rows=15)
    vin = "1M8GDM9AXKP042781"
    folder = settings.output_dir / vin
    result = sink.statuses[-1][2]
    assert Path(result["csv"]).parent == folder
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [
            "car.json",
            Path(result["csv"]).name,
            Path(result["report"]).name,
            Path(result["csv"]).name.replace("data.csv", "summary.json"),
        ]
    )
    car = json.loads((folder / "car.json").read_text())
    assert car["vin"] == vin and car["year"] == 1989 and car["make"] is None  # offline decode: year only (not in table)
    assert sink.infos[0]["car"]["vin"] == vin
    summary = json.loads(next(folder.glob("*_summary.json")).read_text())
    assert summary["vin"] == vin and summary["rows"] == 15 and summary["verdict"] in {"ok", "warn", "crit"}
    assert "Car: " in Path(result["report"]).read_text() and vin in Path(result["report"]).read_text()
    assert session.car.vin == vin


def test_unreadable_vin_logs_under_unknown_car(settings):
    class NoVin(FakeCar):
        def query(self, cmd):
            return obd.OBDResponse() if cmd.name == "VIN" else super().query(cmd)

    run_session(replace(settings, com="FAKE0", baud=38400), NoVin(), rows=5)
    assert (settings.output_dir / "unknown-car").is_dir() and not (settings.output_dir / "car.json").exists()


def test_two_sessions_same_car_share_a_folder_and_keep_nickname(settings):
    cfg = replace(settings, com="FAKE0", baud=38400)
    run_session(cfg, FakeCar(), rows=5)
    Garage(cfg.output_dir).rename("1M8GDM9AXKP042781", "Daily")
    time.sleep(1.1)  # file names are stamped to the second
    run_session(cfg, FakeCar(), rows=5)
    garage = Garage(cfg.output_dir)
    assert len(garage.cars()) == 1 and len(garage.sessions("1M8GDM9AXKP042781")) == 2
    assert garage.load("1M8GDM9AXKP042781").nickname == "Daily"


def test_vin_lookup_names_the_car_mid_session_without_blocking_the_start(settings):
    cfg = replace(settings, com="FAKE0", baud=38400, lookup_vin=True)
    stop = threading.Event()
    sink = RecordingSink(stop, 300)
    lookups = []

    def lookup(vin):
        lookups.append(vin)
        return CarInfo(vin, 2019, "Hyundai", "Sonata", None, "2.4 L 4-cyl", "nhtsa")

    Session(cfg, sink, stop, connector=lambda _p, _b: FakeCar(), notifier=lambda _l: None, vin_lookup=lookup).run()
    assert lookups == ["1M8GDM9AXKP042781"]
    assert sink.infos[0]["car"]["model"] is None  # the first info does not wait for the network
    assert sink.infos[-1]["car"]["title"] == "2019 Hyundai Sonata"
    assert json.loads((cfg.output_dir / "1M8GDM9AXKP042781" / "car.json").read_text())["model"] == "Sonata"


def test_lookup_failure_or_disabled_changes_nothing(settings):
    cfg = replace(settings, com="FAKE0", baud=38400, lookup_vin=True)
    stop = threading.Event()
    sink = RecordingSink(stop, 50)
    Session(
        cfg, sink, stop, connector=lambda _p, _b: FakeCar(), notifier=lambda _l: None, vin_lookup=lambda _v: None
    ).run()
    assert len(sink.infos) == 1 and sink.statuses[-1][0] == "finished"
    called = []
    run_session(replace(cfg, lookup_vin=False), FakeCar(), rows=5)  # fixture notifier; no network attempted
    assert called == []


def test_saved_limits_apply_to_the_session_and_are_reported(settings):
    from obd_dashboard.userconfig import UserConfig

    vin = "1M8GDM9AXKP042781"
    cfg = replace(settings, com="FAKE0", baud=38400)
    config = UserConfig(cfg.output_dir)
    config.set_thresholds({"coolant_warn_c": 90, "coolant_crit_c": 99})  # everywhere: the fake car heats past 102
    config.set_thresholds({"fuel_low_pct": 30}, vin)  # this car only
    session, sink = run_session(cfg, FakeCar(), rows=30)
    assert session.limits.coolant_warn_c == 90 and session.limits.fuel_low_pct == 30
    assert sink.infos[0]["thresholds"]["coolant_crit_c"] == 99
    coolant = [e for e in sink.events if isinstance(e, dict) and e["msg"].startswith("Coolant")]
    assert coolant[0]["level"] == "WARN" and any(e["level"] == "CRIT" for e in coolant)  # WARN from 90, CRIT from 99
    assert all("overheating" not in e["msg"] for e in coolant if e["level"] == "WARN")
    report = Path(sink.statuses[-1][2]["report"]).read_text()
    assert "Alert limits: coolant_warn_c=90, coolant_crit_c=99, fuel_low_pct=30" in report


def test_unchanged_settings_report_defaults_and_leave_tuning_alone(settings):
    cfg = replace(settings, com="FAKE0", baud=38400)
    session, sink = run_session(cfg, FakeCar(), rows=5)
    assert session.tune == cfg.tuning
    assert "Alert limits: defaults" in Path(sink.statuses[-1][2]["report"]).read_text()


def test_saved_advanced_options_override_tuning_but_cli_off_switches_win(settings):
    from obd_dashboard.userconfig import UserConfig

    cfg = replace(settings, com="FAKE0", baud=38400, beep=True)
    UserConfig(cfg.output_dir).set_advanced({"extra_per_loop": 7, "beep": False, "lookup_vin": False})
    stop = threading.Event()
    session = Session(cfg, RecordingSink(stop, 3), stop, connector=lambda _p, _b: FakeCar())
    assert session.tune.extra_per_loop == 7 and session.tune.slow_every == cfg.tuning.slow_every
    assert session._lookup_vin is False
    # saved beep=False silences the default notifier even though the command line did not say --no-beep
    assert session._notify.__name__ != "beep"
    session.run()


# --- polling speed ----------------------------------------------------------------------------------------------

FAST_SENSORS = {"RPM", "SPEED", "ENGINE_LOAD", "THROTTLE_POS", "INTAKE_PRESSURE", "TIMING_ADVANCE", "SHORT_FUEL_TRIM_1"}


class SwitchCar(FakeCar):
    """Remembers python-OBD's `fast` switch and counts queries. With `breaks_fast`, the fast sensors go quiet in it."""

    def __init__(self, breaks_fast=False):
        super().__init__()
        self.fast = False
        self.breaks_fast = breaks_fast
        self.asked: dict[str, int] = {}

    def query(self, cmd, force=False):
        self.asked[cmd.name] = self.asked.get(cmd.name, 0) + 1
        if self.breaks_fast and self.fast and cmd.name in FAST_SENSORS:
            return obd.OBDResponse()
        return super().query(cmd, force)


def _report_of(sink):
    return Path(sink.statuses[-1][2]["report"]).read_text()


def test_fast_adapter_mode_is_on_after_the_careful_start(settings):
    car = SwitchCar()
    _, sink = run_session(replace(settings, com="FAKE0"), car, rows=12)
    assert car.fast is True and "Adapter mode: fast" in _report_of(sink)


def test_fast_adapter_mode_can_be_switched_off(settings):
    car = SwitchCar()
    cfg = replace(settings, com="FAKE0", tuning=replace(settings.tuning, fast_adapter=False))
    _, sink = run_session(cfg, car, rows=12)
    assert car.fast is False and "Adapter mode: standard" in _report_of(sink)


def test_session_drops_back_when_fast_mode_makes_the_sensors_go_quiet(settings):
    car = SwitchCar(breaks_fast=True)
    session, sink = run_session(replace(settings, com="FAKE0"), car, rows=20)
    assert car.fast is False and "switched to the standard mode" in _report_of(sink)
    assert sink.rows[-1]["values"]["RPM"] is not None  # and the readings are back
    assert "lost" not in sink.states


def test_steady_sensors_are_read_less_often_than_the_fast_ones(settings):
    car = SwitchCar()
    cfg = replace(settings, com="FAKE0", tuning=replace(settings.tuning, steady_every=1000.0))
    run_session(cfg, car, rows=15)
    assert car.asked["RPM"] >= 15 and car.asked["COOLANT_TEMP"] <= 3  # the start-up pass, the first cycle, the end
    assert car.asked["CONTROL_MODULE_VOLTAGE"] <= 3


def test_rows_carry_fractions_of_a_second(settings):
    _, sink = run_session(replace(settings, com="FAKE0"), FakeCar(), rows=5)
    assert all(isinstance(row["t"], float) for row in sink.rows)
    assert all(abs(row["t"] * 100 - round(row["t"] * 100)) < 1e-6 for row in sink.rows)  # two decimals

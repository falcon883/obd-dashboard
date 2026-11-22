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
from tests.fakes import FakeCar


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

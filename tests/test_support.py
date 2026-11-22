"""`obd-dashboard support`: the anonymous report people attach to bug reports."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, List

import pytest

from obd_dashboard import cli, support
from obd_dashboard.vin import model_year
from tests.fakes import FakeCar

FULL_VIN = "1M8GDM9AXKP042781"
NOW = datetime.datetime(2026, 11, 22, 9, 30, 0)


def _run(tmp_path: Path, car: Any) -> tuple[int, dict]:
    out = tmp_path / "report.json"
    code = support.run(None, 0, out, opener=lambda port, baud: car, now=lambda: NOW)
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_report_describes_link_vehicle_and_sensors(tmp_path: Path) -> None:
    car = FakeCar()
    code, report = _run(tmp_path, car)
    assert code == 0
    assert car.closed
    assert report["schema"] == support.SCHEMA
    assert report["created"] == "2026-11-22T09:30:00"
    assert report["link"]["connected"] is True
    assert "CAN 11/500" in report["link"]["protocol"]
    assert report["link"]["elm_version"] == "ELM327 v1.5"
    names = {s["name"]: s for s in report["supported"]}
    assert names["RPM"]["answers"] is True
    assert "answers" not in names["VIN"]  # only live sensors are probed for a real answer
    assert report["monitors"]


def test_report_keeps_only_maker_code_and_year_of_the_vin(tmp_path: Path) -> None:
    _, report = _run(tmp_path, FakeCar())
    vehicle = report["vehicle"]
    assert vehicle["vin_maker_code"] == FULL_VIN[:3]
    assert vehicle["model_year"] == model_year(FULL_VIN)
    text = json.dumps(report)
    assert FULL_VIN not in text
    assert FULL_VIN[-8:] not in text  # no tail of the VIN either
    assert "FAKE0" not in text  # the port name stays out


def test_unreachable_adapter_still_writes_a_partial_report(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    code = support.run(None, 0, out, opener=lambda port, baud: None, now=lambda: NOW)
    report = json.loads(out.read_text(encoding="utf-8"))
    assert code == 1
    assert report["link"] == {"connected": False}
    assert "serial_ports" in report
    assert report["python"]


def test_connection_is_closed_even_if_collecting_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    car = FakeCar()

    def boom(conn: Any) -> dict:
        raise RuntimeError("adapter fell over")

    monkeypatch.setattr(support, "collect", boom)
    with pytest.raises(RuntimeError):
        support.run(None, 0, tmp_path / "r.json", opener=lambda p, b: car, now=lambda: NOW)
    assert car.closed


def test_never_asks_the_car_to_clear_codes(tmp_path: Path) -> None:
    asked: List[str] = []

    class Spy(FakeCar):
        def query(self, cmd: Any) -> Any:
            asked.append(cmd.name)
            return super().query(cmd)

    _run(tmp_path, Spy())
    assert asked
    assert "CLEAR_DTC" not in asked


def test_default_file_name_uses_the_timestamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    support.run(None, 0, None, opener=lambda p, b: None, now=lambda: NOW)
    assert (tmp_path / "obd-support-20261122_093000.json").exists()


def test_cli_wires_up_the_support_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict = {}

    def fake_run(port: Any, baud: int, out: Any) -> int:
        seen.update(port=port, baud=baud, out=out)
        return 0

    monkeypatch.setattr(support, "run", fake_run)
    out = tmp_path / "x.json"
    assert cli.main(["support", "--com", "COM4", "--baud", "38400", "--out", str(out)]) == 0
    assert seen == {"port": "COM4", "baud": 38400, "out": out}

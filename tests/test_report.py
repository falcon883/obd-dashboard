from __future__ import annotations

import csv

import pytest

from obd_dashboard.report import SessionFiles, Stat, SummaryData, column_name, csv_fields, render_summary


def test_column_name_adds_unit_but_never_doubles_it():
    units = {"COOLANT_TEMP": "degree_Celsius", "RPM": "revolutions_per_minute", "FUEL_STATUS": "x"}
    assert column_name("COOLANT_TEMP", units) == "coolant_temp_c"
    assert column_name("RPM", units) == "rpm"  # not rpm_rpm
    assert column_name("FUEL_STATUS", units) == "fuel_status"
    assert column_name("VIN", units) == "vin"


def test_csv_fields_layout():
    fields = csv_fields(["RPM", "SPEED"], {"RPM": "revolutions_per_minute"}, ["total", "cyl2"])
    assert fields[:3] == ["time", "elapsed_s", "rpm"]
    assert "battery_v" in fields and fields[-2:] == ["misfire_cyl2_cur", "misfire_total_cur"]


def test_stat():
    s = Stat()
    for v in (2.0, 4.0, 9.0):
        s.add(v)
    assert (s.lo, s.hi, s.mean, s.n) == (2.0, 9.0, 5.0, 3)
    assert Stat().mean != Stat().mean  # NaN when empty


def test_session_files_write_and_always_close(tmp_path):
    with pytest.raises(RuntimeError, match="boom"), SessionFiles(tmp_path / "out", stamp="t1") as files:
        files.log("hello")
        files.start_csv(["a", "b"])
        files.write_row({"a": 1, "b": 2, "ignored": 3})
        raise RuntimeError("boom")
    assert files._report.closed and files._csv_file.closed
    assert (tmp_path / "out" / "t1_report.txt").read_text() == "hello\n"
    rows = list(csv.DictReader((tmp_path / "out" / "t1_data.csv").open()))
    assert rows == [{"a": "1", "b": "2"}]


def test_write_row_requires_start_csv(tmp_path):
    with SessionFiles(tmp_path) as files, pytest.raises(RuntimeError):
        files.write_row({})


def test_render_summary():
    stat = Stat()
    stat.add(700.0)
    stat.add(800.0)
    text = "\n".join(
        render_summary(
            SummaryData(
                worst=1,
                duration_s=120,
                loops=100,
                start_cool=48.0,
                warm={70: 60.0, 80: 90.0},
                end_codes={"stored": [], "pending": [], "mil": False},
                misfire_start=3.0,
                misfire_end=5.0,
                monitor_failures=["X: bad"],
                alerts_raised=["[WARN] hot"],
                sensors=["RPM", "SPEED"],
                units={"RPM": "revolutions_per_minute"},
                stats={"RPM": stat},
                static_start={"WARMUPS": 42},
                static_end={"WARMUPS": 43},
            )
        )
    )
    assert "WARNINGS - see alerts" in text
    assert "start 48C" in text and "70C at 1.0 min" in text
    assert "Mode 06 failures at end: X: bad" in text
    assert "RPM" in text and "750.00" in text and "SPEED" not in text.split("sensor")[-1]
    assert "WARMUPS 42 -> 43" in text

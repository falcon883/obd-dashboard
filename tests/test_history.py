"""History: per-drive numbers from CSV logs, and the endpoint that serves them."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

from obd_dashboard.garage import Garage
from obd_dashboard.history import History, drive_stats

COLUMNS = ["elapsed_s", "rpm", "speed_kph", "coolant_temp_c", "battery_v", "long_fuel_trim_1_pct"]


def write_log(path: Path, rows: List[Dict[str, Any]], columns: List[str] = COLUMNS) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:  # newline="": no CRLF surprises on Windows
        writer = csv.DictWriter(handle, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows(rows)
    return path


def cold_drive(seconds: int = 900, start: float = 30.0) -> List[Dict[str, Any]]:
    """Cold start, climbs 0.1 C per second to 85, idles for the first 100 s then drives at 60 km/h."""
    rows = []
    for t in range(seconds):
        rows.append(
            {
                "elapsed_s": t, "rpm": 800 if t < 100 else 1800, "speed_kph": 0 if t < 100 else 60,
                "coolant_temp_c": min(85.0, start + t * 0.1), "battery_v": 14.2, "long_fuel_trim_1_pct": 2.0,
            }
        )  # fmt: skip
    return rows


def test_numbers_for_a_cold_drive(tmp_path):
    stats = drive_stats(write_log(tmp_path / "d.csv", cold_drive()))
    assert stats["rows"] == 900 and stats["duration_s"] == 899
    assert stats["start_coolant_c"] == 30.0 and stats["coolant_max_c"] == 85.0
    assert stats["warm_70_min"] == round(400 / 60, 1) and stats["warm_80_min"] == round(500 / 60, 1)
    assert stats["battery_avg_v"] == 14.2 and stats["ltft_avg_pct"] == 2.0
    assert stats["distance_km"] == round(60 * 799 / 3600, 1)  # 799 s at 60 km/h


def test_warm_idle_rpm_only_counts_a_warm_engine_standing_still(tmp_path):
    rows = [
        {"elapsed_s": t, "rpm": 720, "speed_kph": 0, "coolant_temp_c": 90, "battery_v": 14.1, "long_fuel_trim_1_pct": 0}
        for t in range(40)
    ]
    rows += [{"elapsed_s": 40 + t, "rpm": 3000, "speed_kph": 0, "coolant_temp_c": 90} for t in range(20)]  # revving
    assert drive_stats(write_log(tmp_path / "d.csv", rows))["warm_idle_rpm"] == 720.0


def test_warm_up_time_is_blank_when_the_engine_started_warm(tmp_path):
    stats = drive_stats(write_log(tmp_path / "d.csv", cold_drive(start=75.0)))
    assert stats["warm_70_min"] is None and stats["warm_80_min"] is None


def test_battery_readings_that_cannot_be_real_are_ignored(tmp_path):
    """Real logs: the computer reports 0.0 V around key-off, and cranking dips to 11 V with the engine stopped."""
    rows = cold_drive(60)
    for row in rows[40:]:
        row["battery_v"] = 0.0
    assert drive_stats(write_log(tmp_path / "d.csv", rows))["battery_avg_v"] == 14.2
    rows = [{"elapsed_s": t, "rpm": 0, "battery_v": 11.0} for t in range(30)]
    assert drive_stats(write_log(tmp_path / "e.csv", rows))["battery_avg_v"] is None  # engine never ran


def test_averages_need_enough_rows_and_gaps_do_not_add_distance(tmp_path):
    few = [{"elapsed_s": t, "rpm": 800, "speed_kph": 50, "battery_v": 14.0} for t in range(5)]
    assert drive_stats(write_log(tmp_path / "a.csv", few))["battery_avg_v"] is None
    gap = [{"elapsed_s": 0, "speed_kph": 100}, {"elapsed_s": 600, "speed_kph": 100}]  # logger paused for 10 minutes
    assert drive_stats(write_log(tmp_path / "b.csv", gap))["distance_km"] == 0.0


def test_missing_columns_and_empty_cells_give_blanks_not_errors(tmp_path):
    rows = [{"elapsed_s": t, "rpm": ""} for t in range(20)]
    stats = drive_stats(write_log(tmp_path / "d.csv", rows, columns=["elapsed_s", "rpm"]))
    assert stats["coolant_max_c"] is None and stats["battery_avg_v"] is None and stats["rows"] == 20
    only_header = write_log(tmp_path / "e.csv", [])
    assert drive_stats(only_header)["rows"] == 0 and drive_stats(only_header)["duration_s"] is None


def make_car(settings, vin="5NPE24AF3GH283081"):
    garage = Garage(settings.output_dir)
    garage.register(vin)
    return garage, vin


def test_drives_are_oldest_first_and_short_ones_stay_out_of_trends(settings):
    garage, vin = make_car(settings)
    folder = garage.car_dir(vin)
    write_log(folder / "20261122_080000_data.csv", cold_drive(900))
    write_log(folder / "20261121_080000_data.csv", cold_drive(30))  # a 30 s test
    (folder / "20261122_080000_summary.json").write_text(json.dumps({"verdict": "warn", "alerts": 2}))
    drives = History(garage).drives(vin)
    assert [d["stamp"] for d in drives] == ["20261121_080000", "20261122_080000"]
    short, long = drives
    assert short["in_trends"] is False and long["in_trends"] is True
    assert long["verdict"] == "warn" and long["alerts"] == 2 and long["complete"] is True
    assert short["complete"] is False and short["verdict"] is None  # a crashed drive still shows up
    assert long["files"]["csv"] == "20261122_080000_data.csv"


def test_cache_follows_the_file(settings):
    garage, vin = make_car(settings)
    path = write_log(garage.car_dir(vin) / "20261122_080000_data.csv", cold_drive(900))
    history = History(garage)
    assert history.drives(vin)[0]["coolant_max_c"] == 85.0
    write_log(path, cold_drive(900, start=60.0)[:700] + [{"elapsed_s": 700, "coolant_temp_c": 99.0}])
    assert history.drives(vin)[0]["coolant_max_c"] == 99.0


def test_an_unreadable_log_is_skipped(settings):
    garage, vin = make_car(settings)
    folder = garage.car_dir(vin)
    (folder / "20261121_080000_data.csv").write_bytes(b"\xff\xfe\x00bad")
    write_log(folder / "20261122_080000_data.csv", cold_drive(900))
    assert [d["stamp"] for d in History(garage).drives(vin)] == ["20261122_080000"]
